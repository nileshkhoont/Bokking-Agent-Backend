from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.models.appointment import Appointment
from app.models.business_config import BusinessConfig
from app.models.call_schedule import CallSchedule
from app.models.person import Person

TOOL_HEADERS = {"X-Tool-Secret": settings.agent_tool_secret}


def _next_monday_9am() -> str:
    now = datetime.now(UTC)
    days_ahead = (0 - now.weekday()) % 7 or 7
    dt = (now + timedelta(days=days_ahead)).replace(hour=9, minute=0, second=0, microsecond=0)
    return dt.isoformat()


def _next_tuesday_10am() -> str:
    now = datetime.now(UTC)
    days_ahead = (1 - now.weekday()) % 7 or 7
    dt = (now + timedelta(days=days_ahead)).replace(hour=10, minute=0, second=0, microsecond=0)
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
async def test_identify_person_never_overwrites_an_existing_different_name(
    client: AsyncClient, business_config: BusinessConfig
):
    """Regression test for the 2026-09-23 incident: a caller asked to check a FRIEND's
    appointment and stated the friend's name ("Dhaval"). identify_person always resolves to the
    real CALLER's own phone number (never the name/number stated in conversation), so passing
    that name through renamed the caller's own record to "Dhaval" — and the tool's response then
    echoed that corrupted name straight back, making the agent believe it actually was looking at
    the friend's data. identify_person must never have the power to rename someone who already
    has a name on file, regardless of whose name gets passed in or why.
    """
    person = Person(phone_number="+15551119000", full_name="Harsh")
    await person.insert()

    response = await client.post(
        "/api/v1/agent-tools/identify-person",
        json={"phone_number": "+15551119000", "full_name": "Dhaval"},
        headers=TOOL_HEADERS,
    )
    assert response.json()["data"]["full_name"] == "Harsh"

    unchanged = await Person.get(person.id)
    assert unchanged.full_name == "Harsh"


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
async def test_identify_person_ignores_expired_appointment_for_has_active_appointment(
    client: AsyncClient, business_config: BusinessConfig
):
    """Regression test for the 2026-09-23 finding: a booked-but-past appointment must never be
    reported as one the caller "still has" — has_active_appointment, appointment_id and
    upcoming_appointments must all ignore it.
    """
    person = Person(phone_number="+15559990001", full_name="Expired Caller")
    await person.insert()
    past_appointment = Appointment(
        person_id=str(person.id),
        appointment_datetime=datetime.now(UTC) - timedelta(days=3),
        status="booked",
        booking_source="inbound_call",
    )
    await past_appointment.insert()

    response = await client.post(
        "/api/v1/agent-tools/identify-person",
        json={"phone_number": "+15559990001"},
        headers=TOOL_HEADERS,
    )
    data = response.json()["data"]
    assert data["has_active_appointment"] is False
    assert data["appointment_id"] is None
    assert data["upcoming_appointments"] == []


@pytest.mark.asyncio
async def test_identify_person_returns_all_upcoming_appointments(
    client: AsyncClient, business_config: BusinessConfig
):
    """A caller with two upcoming appointments must get both back, with real appointment_ids,
    so the agent can match whichever one the caller describes later in the call and act on the
    correct one — never just the single most-recent/farthest-future appointment.
    """
    phone = "+15559990002"
    first_booked = await client.post(
        "/api/v1/agent-tools/book-appointment",
        json={"phone_number": phone, "requested_datetime": _next_monday_9am()},
        headers=TOOL_HEADERS,
    )
    second_booked = await client.post(
        "/api/v1/agent-tools/book-appointment",
        json={"phone_number": phone, "requested_datetime": _next_tuesday_10am()},
        headers=TOOL_HEADERS,
    )
    assert first_booked.json()["success"] is True
    assert second_booked.json()["success"] is True
    first_id = first_booked.json()["data"]["appointment_id"]
    second_id = second_booked.json()["data"]["appointment_id"]

    response = await client.post(
        "/api/v1/agent-tools/identify-person", json={"phone_number": phone}, headers=TOOL_HEADERS
    )
    data = response.json()["data"]
    assert data["has_active_appointment"] is True
    upcoming_ids = {a["appointment_id"] for a in data["upcoming_appointments"]}
    assert upcoming_ids == {first_id, second_id}
    # The most recently BOOKED one (second_id, booked after first_id) is what the flat
    # appointment_id/appointment_datetime_ist fields must reflect for Step 0's single mention —
    # not whichever happens to be furthest in the future.
    assert data["appointment_id"] == second_id


@pytest.mark.asyncio
async def test_cancel_appointment_with_multiple_upcoming_requires_explicit_id(
    client: AsyncClient, business_config: BusinessConfig
):
    """With two upcoming appointments and no appointment_id supplied, cancel_appointment must
    refuse rather than guess — and hand back the full list so the agent can ask the caller which
    one, then retry with the right id.
    """
    phone = "+15559990003"
    first = await client.post(
        "/api/v1/agent-tools/book-appointment",
        json={"phone_number": phone, "requested_datetime": _next_monday_9am()},
        headers=TOOL_HEADERS,
    )
    second = await client.post(
        "/api/v1/agent-tools/book-appointment",
        json={"phone_number": phone, "requested_datetime": _next_tuesday_10am()},
        headers=TOOL_HEADERS,
    )
    first_id = first.json()["data"]["appointment_id"]
    second_id = second.json()["data"]["appointment_id"]

    ambiguous = await client.post(
        "/api/v1/agent-tools/cancel-appointment",
        json={"phone_number": phone},
        headers=TOOL_HEADERS,
    )
    ambiguous_data = ambiguous.json()
    assert ambiguous_data["success"] is False
    returned_ids = {a["appointment_id"] for a in ambiguous_data["data"]["upcoming_appointments"]}
    assert returned_ids == {first_id, second_id}

    # Both appointments must still be untouched — the ambiguous request must not have guessed.
    still_first = await Appointment.get(first_id)
    still_second = await Appointment.get(second_id)
    assert still_first.status == "booked"
    assert still_second.status == "booked"

    # With 2+ upcoming appointments, appointment_id alone (no expected_appointment_datetime) is
    # no longer enough — it must be refused rather than silently trusted.
    id_only = await client.post(
        "/api/v1/agent-tools/cancel-appointment",
        json={"phone_number": phone, "appointment_id": first_id},
        headers=TOOL_HEADERS,
    )
    assert id_only.json()["success"] is False
    still_first_again = await Appointment.get(first_id)
    assert still_first_again.status == "booked"

    # Now cancel explicitly by id + its matching expected_appointment_datetime — must succeed
    # and leave the other one alone.
    cancelled = await client.post(
        "/api/v1/agent-tools/cancel-appointment",
        json={
            "phone_number": phone,
            "appointment_id": first_id,
            "expected_appointment_datetime": _next_monday_9am(),
        },
        headers=TOOL_HEADERS,
    )
    assert cancelled.json()["success"] is True
    assert cancelled.json()["data"]["appointment_id"] == first_id

    untouched = await Appointment.get(second_id)
    assert untouched.status == "booked"


@pytest.mark.asyncio
async def test_reschedule_appointment_with_multiple_upcoming_requires_explicit_id(
    client: AsyncClient, business_config: BusinessConfig
):
    phone = "+15559990004"
    first = await client.post(
        "/api/v1/agent-tools/book-appointment",
        json={"phone_number": phone, "requested_datetime": _next_monday_9am()},
        headers=TOOL_HEADERS,
    )
    await client.post(
        "/api/v1/agent-tools/book-appointment",
        json={"phone_number": phone, "requested_datetime": _next_tuesday_10am()},
        headers=TOOL_HEADERS,
    )
    first_id = first.json()["data"]["appointment_id"]

    ambiguous = await client.post(
        "/api/v1/agent-tools/reschedule-appointment",
        json={"phone_number": phone, "new_appointment_datetime": _next_monday_9am()},
        headers=TOOL_HEADERS,
    )
    assert ambiguous.json()["success"] is False
    assert "upcoming_appointments" in ambiguous.json()["data"]

    # appointment_id alone, with 2+ upcoming appointments and no expected_appointment_datetime,
    # must also be refused — not silently trusted.
    new_time = (datetime.fromisoformat(_next_monday_9am()) + timedelta(hours=1)).isoformat()
    id_only = await client.post(
        "/api/v1/agent-tools/reschedule-appointment",
        json={
            "phone_number": phone,
            "appointment_id": first_id,
            "new_appointment_datetime": new_time,
        },
        headers=TOOL_HEADERS,
    )
    assert id_only.json()["success"] is False

    # id + its matching expected_appointment_datetime resolves it correctly.
    rescheduled = await client.post(
        "/api/v1/agent-tools/reschedule-appointment",
        json={
            "phone_number": phone,
            "appointment_id": first_id,
            "expected_appointment_datetime": _next_monday_9am(),
            "new_appointment_datetime": new_time,
        },
        headers=TOOL_HEADERS,
    )
    assert rescheduled.json()["success"] is True


@pytest.mark.asyncio
async def test_reschedule_appointment_rejects_id_datetime_mismatch(
    client: AsyncClient, business_config: BusinessConfig
):
    """Regression test for the 2026-09-23 incident: the agent confirmed "1:00 PM" out loud to
    the caller, then sent a DIFFERENT appointment's id (the 11:00 AM one) to reschedule_appointment
    — silently rescheduling the wrong appointment while the one the caller actually asked about
    sat untouched. When expected_appointment_datetime is given, the backend must verify it
    matches appointment_id's real stored datetime before doing anything, and refuse otherwise —
    a prompt-only "please double check" instruction already proved insufficient in a real call.
    """
    phone = "+15559990010"
    first = await client.post(
        "/api/v1/agent-tools/book-appointment",
        json={"phone_number": phone, "requested_datetime": _next_monday_9am()},
        headers=TOOL_HEADERS,
    )
    second = await client.post(
        "/api/v1/agent-tools/book-appointment",
        json={"phone_number": phone, "requested_datetime": _next_tuesday_10am()},
        headers=TOOL_HEADERS,
    )
    first_id = first.json()["data"]["appointment_id"]
    second_id = second.json()["data"]["appointment_id"]

    # Agent confirmed the FIRST appointment's time out loud, but (by mistake) sends the
    # SECOND appointment's id — exactly the failure mode observed in the real call.
    mismatched = await client.post(
        "/api/v1/agent-tools/reschedule-appointment",
        json={
            "phone_number": phone,
            "appointment_id": second_id,
            "expected_appointment_datetime": _next_monday_9am(),
            "new_appointment_datetime": (
                datetime.fromisoformat(_next_monday_9am()) + timedelta(hours=2)
            ).isoformat(),
        },
        headers=TOOL_HEADERS,
    )
    assert mismatched.json()["success"] is False
    assert "upcoming_appointments" in mismatched.json()["data"]

    # Neither appointment was touched by the rejected call.
    still_first = await Appointment.get(first_id)
    still_second = await Appointment.get(second_id)
    assert still_first.status == "booked"
    assert still_second.status == "booked"

    # The correctly-paired id + datetime succeeds normally.
    matched = await client.post(
        "/api/v1/agent-tools/reschedule-appointment",
        json={
            "phone_number": phone,
            "appointment_id": first_id,
            "expected_appointment_datetime": _next_monday_9am(),
            "new_appointment_datetime": (
                datetime.fromisoformat(_next_monday_9am()) + timedelta(hours=2)
            ).isoformat(),
        },
        headers=TOOL_HEADERS,
    )
    assert matched.json()["success"] is True


@pytest.mark.asyncio
async def test_cancel_appointment_rejects_id_datetime_mismatch(
    client: AsyncClient, business_config: BusinessConfig
):
    phone = "+15559990011"
    first = await client.post(
        "/api/v1/agent-tools/book-appointment",
        json={"phone_number": phone, "requested_datetime": _next_monday_9am()},
        headers=TOOL_HEADERS,
    )
    second = await client.post(
        "/api/v1/agent-tools/book-appointment",
        json={"phone_number": phone, "requested_datetime": _next_tuesday_10am()},
        headers=TOOL_HEADERS,
    )
    first_id = first.json()["data"]["appointment_id"]
    second_id = second.json()["data"]["appointment_id"]

    mismatched = await client.post(
        "/api/v1/agent-tools/cancel-appointment",
        json={
            "phone_number": phone,
            "appointment_id": second_id,
            "expected_appointment_datetime": _next_monday_9am(),
        },
        headers=TOOL_HEADERS,
    )
    assert mismatched.json()["success"] is False

    still_second = await Appointment.get(second_id)
    assert still_second.status == "booked"

    matched = await client.post(
        "/api/v1/agent-tools/cancel-appointment",
        json={
            "phone_number": phone,
            "appointment_id": first_id,
            "expected_appointment_datetime": _next_monday_9am(),
        },
        headers=TOOL_HEADERS,
    )
    assert matched.json()["success"] is True


@pytest.mark.asyncio
async def test_reschedule_appointment_ignores_unresolved_placeholder_expected_datetime(
    client: AsyncClient, business_config: BusinessConfig
):
    """When there's only one appointment (no disambiguation needed), the agent legitimately has
    no reason to fill expected_appointment_datetime — Edesy then posts the literal unrendered
    token, which must be treated as "not provided", never as a 422 or a real mismatch.
    """
    booked = await client.post(
        "/api/v1/agent-tools/book-appointment",
        json={"phone_number": "+15559990012", "requested_datetime": _next_monday_9am()},
        headers=TOOL_HEADERS,
    )
    appointment_id = booked.json()["data"]["appointment_id"]

    response = await client.post(
        "/api/v1/agent-tools/reschedule-appointment",
        json={
            "phone_number": "+15559990012",
            "appointment_id": appointment_id,
            "expected_appointment_datetime": "{{expected_appointment_datetime}}",
            "new_appointment_datetime": _next_tuesday_10am(),
        },
        headers=TOOL_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["success"] is True


@pytest.mark.asyncio
async def test_reschedule_appointment_id_alone_is_never_trusted_with_multiple_upcoming(
    client: AsyncClient, business_config: BusinessConfig
):
    """Regression test for the 2026-09-23 recurrence: the FIRST version of this guard only ran
    when the agent chose to send expected_appointment_datetime, which it simply omitted in the
    very next real call — appointment_id alone (no expected_appointment_datetime at all, not
    even an unresolved placeholder) was enough to silently reschedule the WRONG one of several
    same-day appointments (12:00 PM got moved instead of the 1:00 PM the caller asked about).
    With 2+ upcoming appointments, appointment_id by itself must now always be refused — the
    check is mandatory, not something the agent can forget to opt into.
    """
    phone = "+15559990020"
    noon = await client.post(
        "/api/v1/agent-tools/book-appointment",
        json={"phone_number": phone, "requested_datetime": _next_monday_9am()},
        headers=TOOL_HEADERS,
    )
    one_pm = await client.post(
        "/api/v1/agent-tools/book-appointment",
        json={"phone_number": phone, "requested_datetime": _next_tuesday_10am()},
        headers=TOOL_HEADERS,
    )
    noon_id = noon.json()["data"]["appointment_id"]
    one_pm_id = one_pm.json()["data"]["appointment_id"]

    # Caller asked to reschedule "1:00 PM"; agent mistakenly sends the noon appointment's id,
    # with no expected_appointment_datetime field in the request at all.
    response = await client.post(
        "/api/v1/agent-tools/reschedule-appointment",
        json={
            "phone_number": phone,
            "appointment_id": noon_id,
            "new_appointment_datetime": (
                datetime.fromisoformat(_next_monday_9am()) + timedelta(days=3)
            ).isoformat(),
        },
        headers=TOOL_HEADERS,
    )
    assert response.json()["success"] is False

    # Neither appointment was touched.
    still_noon = await Appointment.get(noon_id)
    still_one_pm = await Appointment.get(one_pm_id)
    assert still_noon.status == "booked"
    assert still_one_pm.status == "booked"


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


@pytest.mark.asyncio
async def test_outbound_call_ignores_spoofed_phone_number_when_edesy_call_id_matches_schedule(
    client: AsyncClient, business_config: BusinessConfig
):
    """Regression test for the phone-number spoofing concern: on an outbound call, identity must
    be resolved from the verified call_schedule (edesy_call_id), never from whatever phone_number
    a tool call carries. A caller claiming to be someone else's number — or a misconfigured
    dashboard that lets the LLM fill in phone_number itself — must not be able to reach a
    different person's appointment.
    """
    real_person = Person(phone_number="+15551110001", full_name="Real Owner")
    await real_person.insert()
    schedule = CallSchedule(
        person_id=str(real_person.id),
        scheduled_at=datetime.now(UTC),
        call_purpose="admin_scheduled",
        requested_by="admin",
        status="in_progress",
        edesy_call_id="sid-spoof-test-1",
    )
    await schedule.insert()

    booked = await client.post(
        "/api/v1/agent-tools/book-appointment",
        json={
            "phone_number": "+15551110001",
            "requested_datetime": _next_monday_9am(),
            "edesy_call_id": "sid-spoof-test-1",
        },
        headers=TOOL_HEADERS,
    )
    assert booked.json()["success"] is True
    appointment_id = booked.json()["data"]["appointment_id"]

    # Attacker claims a different phone_number but is still on the SAME verified call.
    spoofed_cancel = await client.post(
        "/api/v1/agent-tools/cancel-appointment",
        json={
            "phone_number": "+15559998888",
            "appointment_id": appointment_id,
            "edesy_call_id": "sid-spoof-test-1",
        },
        headers=TOOL_HEADERS,
    )
    assert spoofed_cancel.json()["success"] is True

    # Prove it acted on the REAL owner's appointment, not a new/different person's.
    attacker_person = await Person.find_one(Person.phone_number == "+15559998888")
    assert attacker_person is None  # no junk Person created for the spoofed number

    appointment = await Appointment.get(appointment_id)
    assert appointment.person_id == str(real_person.id)
    assert appointment.status == "cancelled"


@pytest.mark.asyncio
async def test_outbound_identify_person_ignores_spoofed_phone_number(
    client: AsyncClient, business_config: BusinessConfig
):
    real_person = Person(phone_number="+15551110002", full_name="Real Owner Two")
    await real_person.insert()
    await _make_appointment_for_identify_test(real_person, _next_monday_9am())
    schedule = CallSchedule(
        person_id=str(real_person.id),
        scheduled_at=datetime.now(UTC),
        call_purpose="admin_scheduled",
        requested_by="admin",
        status="in_progress",
        edesy_call_id="sid-spoof-test-2",
    )
    await schedule.insert()

    response = await client.post(
        "/api/v1/agent-tools/identify-person",
        json={"phone_number": "+15559997777", "edesy_call_id": "sid-spoof-test-2"},
        headers=TOOL_HEADERS,
    )
    data = response.json()["data"]
    assert data["person_id"] == str(real_person.id)
    assert data["full_name"] == "Real Owner Two"
    assert data["has_active_appointment"] is True


async def _make_appointment_for_identify_test(person: Person, requested_datetime: str) -> None:
    from app.core.constants import AppointmentStatus, BookingSource

    appointment = Appointment(
        person_id=str(person.id),
        appointment_datetime=datetime.fromisoformat(requested_datetime),
        status=AppointmentStatus.booked,
        booking_source=BookingSource.inbound_call,
    )
    await appointment.insert()


@pytest.mark.asyncio
async def test_inbound_call_has_no_schedule_so_phone_number_is_still_trusted(
    client: AsyncClient, business_config: BusinessConfig
):
    """No call_schedule exists for inbound calls (Edesy never sends a call.started webhook), so
    there's nothing to verify against — the fallback to phone_number-based lookup must still work
    normally, unaffected by the edesy_call_id cross-check.
    """
    response = await client.post(
        "/api/v1/agent-tools/identify-person",
        json={
            "phone_number": "+15551110099",
            "full_name": "Inbound Caller",
            "edesy_call_id": "sid-genuinely-inbound-no-schedule",
        },
        headers=TOOL_HEADERS,
    )
    data = response.json()["data"]
    assert data["full_name"] == "Inbound Caller"
    person = await Person.find_one(Person.phone_number == "+15551110099")
    assert person is not None
    assert str(person.id) == data["person_id"]
