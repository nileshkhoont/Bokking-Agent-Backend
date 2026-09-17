from datetime import UTC, datetime, timedelta

import pytest

from app.models.business_config import BusinessConfig
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
