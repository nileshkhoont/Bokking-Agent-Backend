from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.models.business_config import BusinessConfig


def _next_monday_9am() -> str:
    now = datetime.now(UTC)
    days_ahead = (0 - now.weekday()) % 7 or 7
    dt = (now + timedelta(days=days_ahead)).replace(hour=9, minute=0, second=0, microsecond=0)
    return dt.isoformat()


@pytest.mark.asyncio
async def test_book_check_and_reschedule_appointment(
    client: AsyncClient, auth_headers: dict, business_config: BusinessConfig
):
    person = await client.post(
        "/api/v1/persons",
        json={"full_name": "Book Me", "phone_number": "+15553334444"},
        headers=auth_headers,
    )
    person_id = person.json()["id"]

    slot_check = await client.post(
        "/api/v1/appointments/check-slot",
        json={"requested_datetime": _next_monday_9am()},
        headers=auth_headers,
    )
    assert slot_check.json()["available"] is True

    booked = await client.post(
        "/api/v1/appointments",
        json={
            "person_id": person_id,
            "appointment_datetime": _next_monday_9am(),
            "booking_source": "admin_scheduled_call",
        },
        headers=auth_headers,
    )
    assert booked.status_code == 201
    appointment_id = booked.json()["id"]
    assert booked.json()["status"] == "booked"

    new_slot = (
        datetime.fromisoformat(_next_monday_9am()) + timedelta(minutes=30)
    ).isoformat()
    rescheduled = await client.post(
        f"/api/v1/appointments/{appointment_id}/reschedule",
        json={"new_appointment_datetime": new_slot},
        headers=auth_headers,
    )
    assert rescheduled.status_code == 200
    assert rescheduled.json()["status"] == "rescheduled"
    assert rescheduled.json()["original_appointment_id"] == appointment_id


@pytest.mark.asyncio
async def test_cancel_appointment(
    client: AsyncClient, auth_headers: dict, business_config: BusinessConfig
):
    person = await client.post(
        "/api/v1/persons",
        json={"full_name": "Cancel Me", "phone_number": "+15556667777"},
        headers=auth_headers,
    )
    booked = await client.post(
        "/api/v1/appointments",
        json={
            "person_id": person.json()["id"],
            "appointment_datetime": _next_monday_9am(),
            "booking_source": "admin_scheduled_call",
        },
        headers=auth_headers,
    )
    appointment_id = booked.json()["id"]

    cancelled = await client.post(
        f"/api/v1/appointments/{appointment_id}/cancel",
        json={"reason": "person no longer needs it"},
        headers=auth_headers,
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
