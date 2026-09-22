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
async def test_list_available_slots_distinguishes_closed_day_from_fully_booked_day(
    client: AsyncClient, business_config: BusinessConfig
):
    """Regression test for the 2026-09-22 call where a caller asked about 25 and 27 September —
    both non-working days — and was told only "koi slots khali nathi", which sounds like the
    clinic is booked out rather than closed. An empty slots list must carry enough information
    to tell the caller which it is, and which days actually are open.
    """
    monday = datetime.fromisoformat(_next_monday_9am())
    closed_day = (monday + timedelta(days=6)).date()  # Sunday — not in business_config
    assert "sunday" not in [d.lower() for d in business_config.working_days]

    closed = await client.post(
        "/api/v1/agent-tools/list-available-slots",
        json={"date": closed_day.isoformat()},
        headers=TOOL_HEADERS,
    )
    closed_data = closed.json()["data"]
    assert closed_data["count"] == 0
    assert closed_data["is_working_day"] is False
    assert "Sunday" in closed_data["closed_reason"]
    assert closed_data["working_days"]  # the agent has real days to offer instead

    open_day = await client.post(
        "/api/v1/agent-tools/list-available-slots",
        json={"date": monday.date().isoformat()},
        headers=TOOL_HEADERS,
    )
    open_data = open_day.json()["data"]
    assert open_data["is_working_day"] is True
    assert open_data["closed_reason"] is None


@pytest.mark.asyncio
async def test_check_slot_availability_reports_working_days_when_closed(
    client: AsyncClient, business_config: BusinessConfig
):
    monday = datetime.fromisoformat(_next_monday_9am())
    closed_dt = (monday + timedelta(days=6)).isoformat()  # Sunday

    response = await client.post(
        "/api/v1/agent-tools/check-slot-availability",
        json={"requested_datetime": closed_dt},
        headers=TOOL_HEADERS,
    )
    data = response.json()["data"]
    assert data["available"] is False
    assert data["working_days"]


@pytest.mark.asyncio
async def test_cancel_appointment_via_fallback_to_active_appointment(
    client: AsyncClient, business_config: BusinessConfig
):
    """Regression test for the 2026-09-22 incident: there was no cancel_appointment tool at all,
    so the agent hallucinated a cancellation success message while the real appointment stayed
    booked. This proves the new tool actually cancels the person's real active appointment even
    without a valid appointment_id — the caller's own misremembered date must never matter.
    """
    booked = await client.post(
        "/api/v1/agent-tools/book-appointment",
        json={"phone_number": "+15557770000", "requested_datetime": _next_monday_9am()},
        headers=TOOL_HEADERS,
    )
    appointment_id = booked.json()["data"]["appointment_id"]

    cancelled = await client.post(
        "/api/v1/agent-tools/cancel-appointment",
        json={"phone_number": "+15557770000", "reason": "caller requested cancellation"},
        headers=TOOL_HEADERS,
    )
    assert cancelled.json()["success"] is True
    assert cancelled.json()["data"]["appointment_id"] == appointment_id
    assert cancelled.json()["data"]["status"] == "cancelled"

    appointment = await Appointment.get(appointment_id)
    assert appointment.status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_appointment_ignores_unresolved_template_reason(
    client: AsyncClient, business_config: BusinessConfig
):
    """Regression test for the 2026-09-22 root cause: Edesy posts an *unfilled* optional Custom
    Function parameter as the literal token rather than omitting the key, so appointment
    6ab231d28faf632c4b6b04b4 was really stored with notes "Cancelled: {{reason}}". That's the same
    mechanism that corrupted a Person's full_name — so no `{{...}}` token may ever be persisted,
    on any field.
    """
    booked = await client.post(
        "/api/v1/agent-tools/book-appointment",
        json={"phone_number": "+15559990000", "requested_datetime": _next_monday_9am()},
        headers=TOOL_HEADERS,
    )
    appointment_id = booked.json()["data"]["appointment_id"]

    cancelled = await client.post(
        "/api/v1/agent-tools/cancel-appointment",
        json={"phone_number": "+15559990000", "reason": "{{reason}}"},
        headers=TOOL_HEADERS,
    )
    assert cancelled.json()["success"] is True

    appointment = await Appointment.get(appointment_id)
    assert appointment.status == "cancelled"
    assert "{{" not in (appointment.notes or "")


@pytest.mark.asyncio
async def test_unresolved_template_phone_number_is_rejected_not_persisted(client: AsyncClient):
    """A *required* field can't be silently dropped: if the dashboard mapping for phone_number is
    wrong, that must fail loudly instead of creating a junk Person keyed by the literal token.
    """
    response = await client.post(
        "/api/v1/agent-tools/identify-person",
        json={"phone_number": "{{call.phone_number}}"},
        headers=TOOL_HEADERS,
    )
    assert response.status_code == 422
    assert await Person.find_one(Person.phone_number == "{{call.phone_number}}") is None


@pytest.mark.asyncio
async def test_cancel_appointment_with_no_active_appointment_fails_cleanly(client: AsyncClient):
    response = await client.post(
        "/api/v1/agent-tools/cancel-appointment",
        json={"phone_number": "+15557780000"},
        headers=TOOL_HEADERS,
    )
    assert response.json()["success"] is False


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
