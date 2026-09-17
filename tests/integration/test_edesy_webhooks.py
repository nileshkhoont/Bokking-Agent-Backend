"""Signature verification + event-handling tests for the Edesy webhook receiver.

Edesy itself can't be exercised without real credentials (none were provided as part of this
project) — these tests build payloads shaped exactly like Edesy's documented webhook format and
sign them with the same HMAC-SHA256 scheme core.webhook_security verifies, rather than mocking
Edesy's API as if it had actually been called.
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.models.call import Call
from app.models.call_schedule import CallSchedule
from app.models.person import Person


def _sign(body: bytes) -> str:
    return hmac.new(settings.edesy_webhook_secret.encode(), body, hashlib.sha256).hexdigest()


async def _post_webhook(client: AsyncClient, payload: dict, sign: bool = True):
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if sign:
        headers["X-Webhook-Signature"] = _sign(body)
    return await client.post("/api/v1/webhooks/edesy", content=body, headers=headers)


@pytest.mark.asyncio
async def test_webhook_rejects_missing_signature(client: AsyncClient):
    response = await _post_webhook(client, {"event": "call.started"}, sign=False)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_signature(client: AsyncClient):
    body = json.dumps({"event": "call.started"}).encode()
    response = await client.post(
        "/api/v1/webhooks/edesy",
        content=body,
        headers={"X-Webhook-Signature": "not-the-right-signature", "Content-Type": "application/json"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_call_started_inbound_creates_person_and_call(client: AsyncClient):
    payload = {
        "event": "call.started",
        "callId": "edesy-call-1",
        "agentId": "agent-1",
        "phoneNumber": "+15551234567",
        "direction": "inbound",
        "startedAt": datetime.now(UTC).isoformat(),
        "context": {},
    }
    response = await _post_webhook(client, payload)
    assert response.status_code == 200

    call = await Call.find_one(Call.edesy_call_id == "edesy-call-1")
    assert call is not None
    assert call.call_type == "inbound"

    person = await Person.find_one(Person.phone_number == "+15551234567")
    assert person is not None
    assert str(person.id) == call.person_id


@pytest.mark.asyncio
async def test_call_ended_stores_transcript_and_recording(client: AsyncClient):
    started_payload = {
        "event": "call.started",
        "callId": "edesy-call-2",
        "agentId": "agent-1",
        "phoneNumber": "+15559876543",
        "direction": "inbound",
        "startedAt": datetime.now(UTC).isoformat(),
        "context": {},
    }
    await _post_webhook(client, started_payload)

    ended_payload = {
        "event": "call.ended",
        "callId": "edesy-call-2",
        "agentId": "agent-1",
        "endedAt": datetime.now(UTC).isoformat(),
        "durationSeconds": 120,
        "transcript": {
            "summary": "Booked an appointment for next week.",
            "turns": [
                {"role": "agent", "content": "Hello!"},
                {"role": "person", "content": "Hi, I'd like to book an appointment."},
            ],
        },
        "recordingUrl": "https://recordings.edesy.in/edesy-call-2.mp3",
    }
    response = await _post_webhook(client, ended_payload)
    assert response.status_code == 200

    call = await Call.find_one(Call.edesy_call_id == "edesy-call-2")
    assert call.duration_seconds == 120
    assert call.transcript_summary == "Booked an appointment for next week."
    assert "Hello!" in call.transcript
    assert call.recording_url.endswith(".mp3")


@pytest.mark.asyncio
async def test_call_failed_triggers_missed_call_retry(client: AsyncClient):
    schedule = CallSchedule(
        person_id="person-x",
        scheduled_at=datetime.now(UTC),
        call_purpose="admin_scheduled",
        requested_by="admin",
        status="in_progress",
        attempt_number=1,
        max_attempts=3,
    )
    await schedule.insert()

    started_payload = {
        "event": "call.started",
        "callId": "edesy-call-3",
        "agentId": "agent-1",
        "phoneNumber": "+15550001111",
        "direction": "outbound",
        "startedAt": datetime.now(UTC).isoformat(),
        "context": {"call_schedule_id": str(schedule.id)},
    }
    await _post_webhook(client, started_payload)

    failed_payload = {
        "event": "call.failed",
        "callId": "edesy-call-3",
        "agentId": "agent-1",
        "failureReason": "no-answer",
        "failedAt": datetime.now(UTC).isoformat(),
    }
    response = await _post_webhook(client, failed_payload)
    assert response.status_code == 200

    original = await CallSchedule.get(schedule.id)
    assert original.status == "missed"

    retry = await CallSchedule.find_one(CallSchedule.parent_schedule_id == str(schedule.id))
    assert retry is not None
    assert retry.attempt_number == 2
    assert retry.call_purpose == "missed_call_retry"
