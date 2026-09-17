from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.models.business_config import BusinessConfig

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
    identify = await client.post(
        "/api/v1/agent-tools/identify-person",
        json={"phone_number": "+15552220000", "full_name": "Flow Caller"},
        headers=TOOL_HEADERS,
    )
    person_id = identify.json()["data"]["person_id"]

    check = await client.post(
        "/api/v1/agent-tools/check-slot-availability",
        json={"requested_datetime": _next_monday_9am()},
        headers=TOOL_HEADERS,
    )
    assert check.json()["data"]["available"] is True

    booked = await client.post(
        "/api/v1/agent-tools/book-appointment",
        json={"person_id": person_id, "requested_datetime": _next_monday_9am()},
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
async def test_log_callback_request_rejects_outside_business_hours(
    client: AsyncClient, business_config: BusinessConfig
):
    identify = await client.post(
        "/api/v1/agent-tools/identify-person",
        json={"phone_number": "+15553330000", "full_name": "Callback Caller"},
        headers=TOOL_HEADERS,
    )
    person_id = identify.json()["data"]["person_id"]

    late_night = datetime.now(UTC) + timedelta(days=1)
    late_night = late_night.replace(hour=23, minute=0, second=0, microsecond=0)

    response = await client.post(
        "/api/v1/agent-tools/log-callback-request",
        json={
            "person_id": person_id,
            "requested_datetime": late_night.isoformat(),
            "source_call_id": "call-1",
        },
        headers=TOOL_HEADERS,
    )
    assert response.json()["success"] is False
