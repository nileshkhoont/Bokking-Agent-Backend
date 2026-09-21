from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.models.appointment import Appointment
from app.models.business_config import BusinessConfig
from app.models.person import Person

TOOL_HEADERS = {"X-Tool-Secret": settings.agent_tool_secret}


def _next_monday_9am() -> str:
    now = datetime.now(UTC)
    days_ahead = (0 - now.weekday()) % 7 or 7
    dt = (now + timedelta(days=days_ahead)).replace(hour=9, minute=0, second=0, microsecond=0)
    return dt.isoformat()


@pytest.mark.asyncio
async def test_agent_tools_reject_missing_secret(client: AsyncClient):
    response = await client.post(
        "/api/v1/agent-tools/identify-person", json={"phone_number": "+15551110000"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_identify_person_creates_record_for_new_caller(client: AsyncClient):
    response = await client.post(
        "/api/v1/agent-tools/identify-person",
        json={"phone_number": "+15551110000", "full_name": "New Caller"},
        headers=TOOL_HEADERS,
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["full_name"] == "New Caller"
    assert data["has_active_appointment"] is False


@pytest.mark.asyncio
async def test_full_inbound_tool_flow_book_then_identify_shows_appointment(
    client: AsyncClient, business_config: BusinessConfig
):
    await client.post(
        "/api/v1/agent-tools/identify-person",
        json={"phone_number": "+15552220000", "full_name": "Flow Caller"},
        headers=TOOL_HEADERS,
    )

    check = await client.post(
        "/api/v1/agent-tools/check-slot-availability",
        json={"requested_datetime": _next_monday_9am()},
        headers=TOOL_HEADERS,
    )
    assert check.json()["data"]["available"] is True

    # book-appointment resolves the person from phone_number itself — this deliberately does NOT
    # pass a person_id, proving a booking succeeds correctly even if identify_person was never
    # called (or its result was never carried forward) earlier in the same conversation.
    booked = await client.post(
        "/api/v1/agent-tools/book-appointment",
        json={"phone_number": "+15552220000", "requested_datetime": _next_monday_9am()},
        headers=TOOL_HEADERS,
    )
    assert booked.json()["success"] is True

    identify_again = await client.post(
        "/api/v1/agent-tools/identify-person",
        json={"phone_number": "+15552220000"},
        headers=TOOL_HEADERS,
    )
    assert identify_again.json()["data"]["has_active_appointment"] is True


@pytest.mark.asyncio
async def test_book_appointment_with_no_prior_identify_person_still_links_real_person(
    client: AsyncClient, business_config: BusinessConfig
):
    """Regression test for the 2026-09-21 incident: a custom agent prompt that never calls
    identify_person (or forgets its result) must still produce an appointment with a real,
    resolvable person_id — not a placeholder like "none" — because book-appointment resolves the
    person from the call's phone number itself, not from anything the LLM claims.
    """
    booked = await client.post(
        "/api/v1/agent-tools/book-appointment",
        json={"phone_number": "+15554440000", "requested_datetime": _next_monday_9am()},
        headers=TOOL_HEADERS,
    )
    assert booked.json()["success"] is True
    appointment_id = booked.json()["data"]["appointment_id"]

    appointment = await Appointment.get(appointment_id)
    assert appointment is not None

    person = await Person.get(appointment.person_id)
    assert person is not None
    assert person.phone_number == "+15554440000"


@pytest.mark.asyncio
async def test_book_appointment_updates_name_for_phone_only_scheduled_call(
    client: AsyncClient, business_config: BusinessConfig
):
    """Regression test: a call scheduled with only a phone number (no name yet) creates a Person
    with no full_name. If the caller states their name during the call and the agent passes it
    to book_appointment, the Person's name must actually get saved — not just spoken back in the
    conversation and then lost.
    """
    person = Person(phone_number="+15556661111")
    await person.insert()
    assert person.full_name is None

    booked = await client.post(
        "/api/v1/agent-tools/book-appointment",
        json={
            "phone_number": "+15556661111",
            "requested_datetime": _next_monday_9am(),
            "full_name": "Harsh",
        },
        headers=TOOL_HEADERS,
    )
    assert booked.json()["success"] is True

    updated = await Person.get(person.id)
    assert updated.full_name == "Harsh"


@pytest.mark.asyncio
async def test_list_available_slots_excludes_booked_time(
    client: AsyncClient, business_config: BusinessConfig
):
    on_date = datetime.fromisoformat(_next_monday_9am()).date().isoformat()

    before = await client.post(
        "/api/v1/agent-tools/list-available-slots", json={"date": on_date}, headers=TOOL_HEADERS
    )
    slots_before = before.json()["data"]["slots"]
    assert any(s["time_ist"] for s in slots_before)  # sanity: got real IST-formatted options

    await client.post(
        "/api/v1/agent-tools/book-appointment",
        json={"phone_number": "+15555550000", "requested_datetime": _next_monday_9am()},
        headers=TOOL_HEADERS,
    )

    after = await client.post(
        "/api/v1/agent-tools/list-available-slots", json={"date": on_date}, headers=TOOL_HEADERS
    )
    slots_after = after.json()["data"]["slots"]
    assert len(slots_after) == len(slots_before) - 1
    booked_iso = _next_monday_9am()
    assert booked_iso not in [s["datetime"] for s in slots_after]


@pytest.mark.asyncio
async def test_log_callback_request_rejects_outside_business_hours(
    client: AsyncClient, business_config: BusinessConfig
):
    await client.post(
        "/api/v1/agent-tools/identify-person",
        json={"phone_number": "+15553330000", "full_name": "Callback Caller"},
        headers=TOOL_HEADERS,
    )

    late_night = datetime.now(UTC) + timedelta(days=1)
    late_night = late_night.replace(hour=23, minute=0, second=0, microsecond=0)

    response = await client.post(
        "/api/v1/agent-tools/log-callback-request",
        json={
            "phone_number": "+15553330000",
            "requested_datetime": late_night.isoformat(),
            "source_call_id": "call-1",
        },
        headers=TOOL_HEADERS,
    )
    assert response.json()["success"] is False
