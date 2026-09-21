from datetime import UTC, datetime, timedelta

import pytest

from app.models.business_config import BusinessConfig, WorkingHours
from app.services.slot_service import slot_service


def _next_weekday_at(hour: int, minute: int, weekday: int) -> datetime:
    """weekday: Monday=0 ... Sunday=6"""
    now = datetime.now(UTC)
    days_ahead = (weekday - now.weekday()) % 7
    days_ahead = days_ahead or 7  # always strictly in the future
    target = now + timedelta(days=days_ahead)
    return target.replace(hour=hour, minute=minute, second=0, microsecond=0)


@pytest.mark.asyncio
async def test_slot_available_within_working_hours(business_config: BusinessConfig):
    monday_9am = _next_weekday_at(9, 0, weekday=0)
    result = await slot_service.check_availability(monday_9am)
    assert result.available is True


@pytest.mark.asyncio
async def test_slot_unavailable_outside_working_hours(business_config: BusinessConfig):
    monday_8pm = _next_weekday_at(20, 0, weekday=0)
    result = await slot_service.check_availability(monday_8pm)
    assert result.available is False
    assert "working hours" in result.reason


@pytest.mark.asyncio
async def test_slot_unavailable_on_non_working_day(business_config: BusinessConfig):
    # business_config fixture only configures Mon-Fri as working days
    saturday_10am = _next_weekday_at(10, 0, weekday=5)
    result = await slot_service.check_availability(saturday_10am)
    assert result.available is False
    assert "closed" in result.reason.lower()


@pytest.mark.asyncio
async def test_slot_unavailable_in_the_past(business_config: BusinessConfig):
    past = datetime.now(UTC) - timedelta(days=1)
    result = await slot_service.check_availability(past)
    assert result.available is False
    assert "past" in result.reason.lower()


@pytest.mark.asyncio
async def test_slot_unavailable_beyond_advance_window(business_config: BusinessConfig):
    too_far = datetime.now(UTC) + timedelta(days=365)
    result = await slot_service.check_availability(too_far)
    assert result.available is False
    assert "advance booking window" in result.reason


@pytest.mark.asyncio
async def test_slot_unavailable_off_boundary(business_config: BusinessConfig):
    monday_905am = _next_weekday_at(9, 5, weekday=0)  # not aligned to 30-min slots
    result = await slot_service.check_availability(monday_905am)
    assert result.available is False
    assert "align" in result.reason


@pytest.mark.asyncio
async def test_multiple_windows_same_day_morning_and_evening():
    """Reproduces the exact reported schedule: Mon/Thu/Sat, 11:00-13:30 AND 17:00-18:30, 20-min
    slots. 13:00 fits (ends 13:20, inside); 13:20 does not (would end 13:40, past closing) even
    though 13:20 itself is inside the window and on the 20-min grid — the last 10 minutes of each
    window (13:20-13:30, 18:20-18:30) must stay unbookable, exactly as specified.
    """
    config = BusinessConfig(
        working_days=["monday", "thursday", "saturday"],
        working_hours=[
            WorkingHours(start="11:00", end="13:30"),
            WorkingHours(start="17:00", end="18:30"),
        ],
        slot_duration_minutes=20,
        buffer_minutes=0,
        holidays=[],
        max_advance_booking_days=30,
        timezone="UTC",
    )
    await config.insert()

    monday_1300 = _next_weekday_at(13, 0, weekday=0)
    assert (await slot_service.check_availability(monday_1300)).available is True

    monday_1320 = _next_weekday_at(13, 20, weekday=0)
    result = await slot_service.check_availability(monday_1320)
    assert result.available is False

    monday_1700 = _next_weekday_at(17, 0, weekday=0)
    assert (await slot_service.check_availability(monday_1700)).available is True

    monday_1500 = _next_weekday_at(15, 0, weekday=0)  # the midday gap between windows
    result = await slot_service.check_availability(monday_1500)
    assert result.available is False

    tuesday_1100 = _next_weekday_at(11, 0, weekday=1)  # not a working day
    result = await slot_service.check_availability(tuesday_1100)
    assert result.available is False


@pytest.mark.asyncio
async def test_list_available_slots_matches_the_reported_schedule():
    """The list-based generator must agree exactly with check_availability's per-slot logic:
    same 7 morning + 4 evening slots as the manual worked example, and a fully-booked slot must
    disappear from the list without needing a separate exists_active_at call per candidate.
    """
    from app.core.constants import AppointmentStatus, BookingSource
    from app.models.appointment import Appointment
    from app.models.person import Person

    config = BusinessConfig(
        working_days=["monday", "thursday", "saturday"],
        working_hours=[
            WorkingHours(start="11:00", end="13:30"),
            WorkingHours(start="17:00", end="18:30"),
        ],
        slot_duration_minutes=20,
        buffer_minutes=0,
        holidays=[],
        max_advance_booking_days=30,
        timezone="UTC",
    )
    await config.insert()

    monday = _next_weekday_at(11, 0, weekday=0)
    slots = await slot_service.list_available_slots(monday.date())
    assert len(slots) == 11  # 7 morning + 4 evening

    person = Person(phone_number="+15556660000")
    await person.insert()
    booked_time = _next_weekday_at(11, 40, weekday=0)
    await Appointment(
        person_id=str(person.id),
        appointment_datetime=booked_time,
        status=AppointmentStatus.booked,
        booking_source=BookingSource.inbound_call,
    ).insert()

    slots_after_booking = await slot_service.list_available_slots(monday.date())
    assert len(slots_after_booking) == 10
    assert booked_time not in slots_after_booking
