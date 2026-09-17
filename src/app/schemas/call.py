from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.core.constants import CallOutcome, CallStatus, CallType, Direction


class TranscriptTurn(BaseModel):
    """Edesy's transcript shape: a summary plus an array of turns — not a single text blob."""

    role: str  # "agent" | "person"
    content: str
    timestamp: datetime | None = None


class CallOut(BaseModel):
    id: str
    call_schedule_id: str | None = None
    person_id: str
    appointment_id: str | None = None
    call_type: CallType
    direction: Direction
    call_status: CallStatus
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_seconds: int | None = None
    transcript: str | None = None
    transcript_summary: str | None = None
    recording_url: str | None = None
    edesy_call_id: str | None = None
    outcome: CallOutcome | None = None
    created_at: datetime


class CallFilterParams(BaseModel):
    date_from: datetime | None = None
    date_to: datetime | None = None
    call_type: CallType | None = None
    call_status: CallStatus | None = None
    outcome: CallOutcome | None = None
    person_id: str | None = None


class DashboardStats(BaseModel):
    booked_appointments: int
    cancelled_appointments: int
    inbound_calls: int
    outbound_calls: int
    admin_scheduled_calls: int
    agent_scheduled_calls: int
    failed_calls: int


class ToolResponse(BaseModel):
    """Generic envelope every agent_tools endpoint returns — kept deliberately simple/flat since
    the Edesy agent reads this mid-conversation, not an admin UI.
    """

    success: bool
    data: dict[str, Any] | None = None
    message: str | None = None
