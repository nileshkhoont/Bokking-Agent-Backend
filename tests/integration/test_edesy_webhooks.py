"""Signature verification + event-handling tests for the Vani/Edesy webhook receiver.

The payload shape used below matches a REAL captured `call.ended` webhook (2026-09-17) — nested
`call`/`agent`/`outcome` objects, `speaker`/`text` transcript turns — not a guessed shape. See
integrations/edesy/webhook_events.py's module docstring for the full context on why this replaced
an earlier, entirely-wrong flat-shape assumption that caused every real webhook to be rejected.
"""

import json
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.models.call import Call
from app.models.call_schedule import CallSchedule
from app.models.person import Person


async def _post_webhook(client: AsyncClient, payload: dict, sign: bool = True):
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if sign:
        headers["Authorization"] = f"Bearer {settings.edesy_webhook_secret}"
    return await client.post("/api/v1/webhooks/edesy", content=body, headers=headers)


def _call_ended_payload(
    call_sid: str,
    phone: str,
    status: str = "completed",
    disposition: str | None = "CALLBACK_SCHEDULED",
    end_reason: str = "USER_REQUEST",
    direction: str = "inbound",
) -> dict:
    return {
        "event": "call.ended",
        "timestamp": datetime.now(UTC).isoformat(),
        "call": {
            "id": "abc123",
            "callSid": call_sid,
            "direction": direction,
            "from": phone,
            "to": "",
            "duration": 35,
            "turnCount": 4,
            "provider": "plivo",
            "llmMode": "gemini-live-3.1",
        },
        "agent": {"id": 47094},
        "outcome": {
            "status": status,
            "disposition": disposition,
            "confidence": 1,
            "endReason": end_reason,
            "endedBy": "agent",
        },
        "data": {},
        "transcript": [
            {"speaker": "agent", "text": "Hello!", "timestamp": datetime.now(UTC).isoformat()},
            {"speaker": "user", "text": "Call me back in 5 minutes.", "timestamp": datetime.now(UTC).isoformat()},
        ],
    }


@pytest.mark.asyncio
async def test_webhook_rejects_missing_signature(client: AsyncClient):
    response = await _post_webhook(client, {"event": "call.ended"}, sign=False)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_signature(client: AsyncClient):
    body = json.dumps({"event": "call.ended"}).encode()
    response = await client.post(
        "/api/v1/webhooks/edesy",
        content=body,
        headers={"Authorization": "Bearer not-the-right-secret", "Content-Type": "application/json"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_call_ended_inbound_creates_person_and_call(client: AsyncClient):
    payload = _call_ended_payload(call_sid="sid-inbound-1", phone="+15551234567")
    response = await _post_webhook(client, payload)
    assert response.status_code == 200

    call = await Call.find_one(Call.edesy_call_id == "sid-inbound-1")
    assert call is not None
    assert call.call_type == "inbound"
    assert call.call_status == "answered"  # outcome.status == "completed"
    assert call.outcome == "callback_requested"  # disposition CALLBACK_SCHEDULED
    assert "Call me back in 5 minutes" in call.transcript

    person = await Person.find_one(Person.phone_number == "+15551234567")
    assert person is not None
    assert str(person.id) == call.person_id


@pytest.mark.asyncio
async def test_call_ended_for_outbound_schedule_marks_completed(client: AsyncClient):
    schedule = CallSchedule(
        person_id="person-x",
        scheduled_at=datetime.now(UTC),
        call_purpose="admin_scheduled",
        requested_by="admin",
        status="in_progress",
        attempt_number=1,
        max_attempts=3,
        edesy_call_id="sid-outbound-1",
    )
    await schedule.insert()

    payload = _call_ended_payload(call_sid="sid-outbound-1", phone="+15559876543", direction="outbound")
    response = await _post_webhook(client, payload)
    assert response.status_code == 200

    call = await Call.find_one(Call.edesy_call_id == "sid-outbound-1")
    assert call.call_schedule_id == str(schedule.id)
    assert call.call_type == "outbound_admin_scheduled"

    updated_schedule = await CallSchedule.get(schedule.id)
    assert updated_schedule.status == "completed"


@pytest.mark.asyncio
async def test_call_ended_failure_triggers_missed_call_retry(client: AsyncClient):
    schedule = CallSchedule(
        person_id="person-y",
        scheduled_at=datetime.now(UTC),
        call_purpose="admin_scheduled",
        requested_by="admin",
        status="in_progress",
        attempt_number=1,
        max_attempts=3,
        edesy_call_id="sid-outbound-2",
    )
    await schedule.insert()

    payload = _call_ended_payload(
        call_sid="sid-outbound-2",
        phone="+15550001111",
        direction="outbound",
        status="no-answer",
        disposition=None,
        end_reason="NO_ANSWER",
    )
    response = await _post_webhook(client, payload)
    assert response.status_code == 200

    call = await Call.find_one(Call.edesy_call_id == "sid-outbound-2")
    assert call.call_status == "no_answer"

    original = await CallSchedule.get(schedule.id)
    assert original.status == "missed"

    retry = await CallSchedule.find_one(CallSchedule.parent_schedule_id == str(schedule.id))
    assert retry is not None
    assert retry.attempt_number == 2
    assert retry.call_purpose == "missed_call_retry"


@pytest.mark.asyncio
async def test_webhook_ignores_unrecognized_event_gracefully(client: AsyncClient):
    """An event name we don't recognize must not 400 — Vani's dashboard would show that as a
    failed delivery, and this is an undocumented API where the shape can change again.
    """
    response = await _post_webhook(client, {"event": "something.new", "data": {}})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_webhook_handles_malformed_call_ended_gracefully(client: AsyncClient):
    """Missing the one required field (call.callSid) must not 500/400 — logged and accepted."""
    response = await _post_webhook(client, {"event": "call.ended", "call": {"from": "+15551112222"}})
    assert response.status_code == 200
    count = await Call.find(Call.person_id != None).count()  # noqa: E711
    assert count == 0


@pytest.mark.asyncio
async def test_call_ended_updates_existing_call_record(client: AsyncClient):
    """A second call.ended for the same callSid (e.g. a retried delivery) updates in place rather
    than creating a duplicate.
    """
    payload = _call_ended_payload(call_sid="sid-dup-1", phone="+15553334444", status="completed")
    await _post_webhook(client, payload)

    payload["transcript"].append({"speaker": "agent", "text": "Extra turn", "timestamp": datetime.now(UTC).isoformat()})
    response = await _post_webhook(client, payload)
    assert response.status_code == 200

    matching = await Call.find(Call.edesy_call_id == "sid-dup-1").to_list()
    assert len(matching) == 1
    assert "Extra turn" in matching[0].transcript
