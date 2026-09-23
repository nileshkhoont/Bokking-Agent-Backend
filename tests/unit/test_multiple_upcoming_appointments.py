"""Regression tests for the 2026-09-23 finding: with more than one booked appointment,
get_active_for_person picked the FARTHEST-future one (not the most recently booked), and
had_active_appointment/{{previous_appointment_status}} could report an appointment as current
even when it was actually in the past. appointment_repository.list_upcoming_for_person and
build_call_variables fix both — see their docstrings for the full reasoning.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.constants import AppointmentStatus, BookingSource
from app.integrations.edesy.prompts.call_variables import build_call_variables
from app.models.appointment import Appointment
from app.models.business_config import BusinessConfig
from app.models.person import Person
from app.repositories.appointment_repository import appointment_repository


async def _make_person(phone_number: str, full_name: str | None = None) -> Person:
    person = Person(phone_number=phone_number, full_name=full_name)
    await person.insert()
    return person


async def _make_appointment(
    person_id: str, when: datetime, status: AppointmentStatus = AppointmentStatus.booked
) -> Appointment:
    appointment = Appointment(
        person_id=person_id,
        appointment_datetime=when,
        status=status,
        booking_source=BookingSource.inbound_call,
    )
    await appointment.insert()
    return appointment


@pytest.mark.asyncio
async def test_list_upcoming_excludes_past_and_cancelled(business_config: BusinessConfig):
    person = await _make_person("+15560000001")
    now = datetime.now(UTC)

    past = await _make_appointment(str(person.id), now - timedelta(days=1))
    future = await _make_appointment(str(person.id), now + timedelta(days=1))
    cancelled_future = await _make_appointment(
        str(person.id), now + timedelta(days=2), status=AppointmentStatus.cancelled
    )

    upcoming = await appointment_repository.list_upcoming_for_person(str(person.id))

    upcoming_ids = {str(a.id) for a in upcoming}
    assert upcoming_ids == {str(future.id)}
    assert str(past.id) not in upcoming_ids
    assert str(cancelled_future.id) not in upcoming_ids


@pytest.mark.asyncio
async def test_list_upcoming_returns_all_future_appointments_sorted_soonest_first(
    business_config: BusinessConfig,
):
    person = await _make_person("+15560000002")
    now = datetime.now(UTC)

    later = await _make_appointment(str(person.id), now + timedelta(days=10))
    sooner = await _make_appointment(str(person.id), now + timedelta(days=2))

    upcoming = await appointment_repository.list_upcoming_for_person(str(person.id))

    assert [str(a.id) for a in upcoming] == [str(sooner.id), str(later.id)]


@pytest.mark.asyncio
async def test_build_call_variables_uses_most_recently_booked_not_farthest_future():
    """The core scenario from the bug report: a caller has two upcoming appointments where the
    one booked LAST (most recently) is NOT the one furthest in the future. Step 0 must mention
    the one actually booked most recently.
    """
    person = Person(phone_number="+15560000003", full_name="Harsh")
    now = datetime.now(UTC)

    farther_but_booked_first = Appointment(
        person_id="irrelevant",
        appointment_datetime=now + timedelta(days=10),
        status=AppointmentStatus.booked,
        booking_source=BookingSource.inbound_call,
    )
    farther_but_booked_first.created_at = now - timedelta(hours=2)

    sooner_but_booked_most_recently = Appointment(
        person_id="irrelevant",
        appointment_datetime=now + timedelta(days=3),
        status=AppointmentStatus.booked,
        booking_source=BookingSource.inbound_call,
    )
    sooner_but_booked_most_recently.created_at = now - timedelta(minutes=5)

    variables = build_call_variables(
        person, [farther_but_booked_first, sooner_but_booked_most_recently]
    )

    assert variables["previous_appointment_status"] == "upcoming"
    from app.utils.datetime_utils import format_ist_human

    assert variables["previous_appointment_datetime_ist"] == format_ist_human(
        sooner_but_booked_most_recently.appointment_datetime
    )


@pytest.mark.asyncio
async def test_build_call_variables_expired_only_when_nothing_upcoming():
    person = Person(phone_number="+15560000004")
    now = datetime.now(UTC)
    expired = Appointment(
        person_id="irrelevant",
        appointment_datetime=now - timedelta(days=5),
        status=AppointmentStatus.booked,
        booking_source=BookingSource.inbound_call,
    )

    variables = build_call_variables(person, [], last_expired_appointment=expired)

    assert variables["previous_appointment_status"] == "expired"
    assert variables["previous_appointment_datetime_ist"] != ""


@pytest.mark.asyncio
async def test_build_call_variables_none_when_no_appointments_at_all():
    person = Person(phone_number="+15560000005")
    variables = build_call_variables(person, [], last_expired_appointment=None)
    assert variables["previous_appointment_status"] == "none"
    assert variables["previous_appointment_datetime_ist"] == ""
