"""Signature verification + event-handling tests for the Vani/Edesy webhook receiver.

The payload shape used below matches a REAL captured `call.ended` webhook (2026-09-17) — nested
`call`/`agent`/`outcome` objects, `speaker`/`text` transcript turns — not a guessed shape. See
integrations/edesy/webhook_events.py's module docstring for the full context on why this replaced
an earlier, entirely-wrong flat-shape assumption that caused every real webhook to be rejected.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.constants import AppointmentStatus, BookingSource
from app.models.appointment import Appointment
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
        edesy_call_id="sid-outbound-1",
    )
    await schedule.insert()

    payload = _call_ended_payload(call_sid="sid-outbound-1", phone="+15559876543", direction="outbound")
    response = await _post_webhook(client, payload)
    assert response.status_code == 200

    call = await Call.find_one(Call.edesy_call_id == "sid-outbound-1")
    assert call.call_schedule_id == str(schedule.id)
    assert call.call_type == "outbound_admin_scheduled"
    # Person picked up but asked for a callback (disposition CALLBACK_SCHEDULED) => "busy".
    assert call.call_status == "busy"

    updated_schedule = await CallSchedule.get(schedule.id)
    assert updated_schedule.status == "completed"


@pytest.mark.asyncio
async def test_outbound_call_answered_normally_stays_answered(client: AsyncClient):
    schedule = CallSchedule(
        person_id="person-w",
        scheduled_at=datetime.now(UTC),
        call_purpose="admin_scheduled",
        requested_by="admin",
        status="in_progress",
        edesy_call_id="sid-outbound-3",
    )
    await schedule.insert()

    payload = _call_ended_payload(
        call_sid="sid-outbound-3",
        phone="+15550003333",
        direction="outbound",
        disposition="APPOINTMENT_BOOKED",
    )
    assert (await _post_webhook(client, payload)).status_code == 200

    call = await Call.find_one(Call.edesy_call_id == "sid-outbound-3")
    assert call.call_status == "answered"


@pytest.mark.asyncio
async def test_call_ended_failure_marks_missed_with_no_retry(client: AsyncClient):
    schedule = CallSchedule(
        person_id="person-y",
        scheduled_at=datetime.now(UTC),
        call_purpose="admin_scheduled",
        requested_by="admin",
        status="in_progress",
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

    # No auto-retry — this was the only call_schedules row for this person.
    remaining = await CallSchedule.find(CallSchedule.person_id == "person-y").count()
    assert remaining == 1


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
async def test_call_ended_backfills_appointment_created_during_the_call(client: AsyncClient):
    """Regression test for the 2026-09-22 incident: agent_tools.py has no way to give
    book_appointment a real calls._id (that document doesn't exist until this webhook runs), so
    Appointment.created_by_call_id must come from here — correlated by person + the appointment
    having been created inside this call's own start/end window — not from anything the LLM
    claimed (observed in production data: "none", "12345", or Edesy's own call id).
    """
    person = Person(phone_number="+15557778888")
    await person.insert()

    appointment = Appointment(
        person_id=str(person.id),
        appointment_datetime=datetime.now(UTC) + timedelta(days=1),
        status=AppointmentStatus.booked,
        booking_source=BookingSource.inbound_call,
        created_by_call_id=None,
    )
    await appointment.insert()

    payload = _call_ended_payload(call_sid="sid-backfill-1", phone="+15557778888")
    response = await _post_webhook(client, payload)
    assert response.status_code == 200

    call = await Call.find_one(Call.edesy_call_id == "sid-backfill-1")
    assert call is not None

    updated_appointment = await Appointment.get(appointment.id)
    assert updated_appointment.created_by_call_id == str(call.id)


@pytest.mark.asyncio
async def test_backfill_disambiguates_same_person_overlapping_calls(client: AsyncClient):
    """The scenario a pure person+time-window heuristic can't safely handle on its own: the same
    person has two calls whose start/end windows overlap, each having booked its own appointment.
    pending_edesy_call_id (Edesy's own callSid, captured at booking time, not LLM-guessed) must
    disambiguate them exactly — appointment A links only to call A, appointment B only to call B,
    even though both appointments were created inside both calls' overlapping time windows.
    """
    person = Person(phone_number="+15559990000")
    await person.insert()

    now = datetime.now(UTC)
    appointment_a = Appointment(
        person_id=str(person.id),
        appointment_datetime=now + timedelta(days=1),
        status=AppointmentStatus.booked,
        booking_source=BookingSource.inbound_call,
        created_by_call_id=None,
        pending_edesy_call_id="sid-overlap-a",
    )
    await appointment_a.insert()

    appointment_b = Appointment(
        person_id=str(person.id),
        appointment_datetime=now + timedelta(days=2),
        status=AppointmentStatus.booked,
        booking_source=BookingSource.inbound_call,
        created_by_call_id=None,
        pending_edesy_call_id="sid-overlap-b",
    )
    await appointment_b.insert()

    # Both calls "end" around the same moment with a long-ish duration, so a naive time-window
    # match alone would see both appointments as plausible candidates for either call.
    payload_a = _call_ended_payload(call_sid="sid-overlap-a", phone="+15559990000")
    payload_a["call"]["duration"] = 600
    await _post_webhook(client, payload_a)

    payload_b = _call_ended_payload(call_sid="sid-overlap-b", phone="+15559990000")
    payload_b["call"]["duration"] = 600
    await _post_webhook(client, payload_b)

    call_a = await Call.find_one(Call.edesy_call_id == "sid-overlap-a")
    call_b = await Call.find_one(Call.edesy_call_id == "sid-overlap-b")

    updated_a = await Appointment.get(appointment_a.id)
    updated_b = await Appointment.get(appointment_b.id)

    assert updated_a.created_by_call_id == str(call_a.id)
    assert updated_b.created_by_call_id == str(call_b.id)
    assert updated_a.created_by_call_id != updated_b.created_by_call_id


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
