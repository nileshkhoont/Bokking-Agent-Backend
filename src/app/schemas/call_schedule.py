from datetime import datetime

from pydantic import BaseModel

from app.core.constants import CallPurpose, CallScheduleStatus, RequestedBy


class CallScheduleCreate(BaseModel):
    """Admin-scheduled call — either from an existing booked appointment or a fresh form
    (PDF §3.1: "from list of already booked appointments of persons or by filling schedule
    appointment form").
    """

    person_id: str
    appointment_id: str | None = None
    scheduled_at: datetime
    admin_instructions: str | None = None


class CallScheduleOut(BaseModel):
    id: str
    person_id: str
    person_full_name: str | None = None
    person_phone_number: str | None = None
    appointment_id: str | None = None
    scheduled_at: datetime
    call_purpose: CallPurpose
    requested_by: RequestedBy
    source_call_id: str | None = None
    admin_instructions: str | None = None
    status: CallScheduleStatus
    created_by: str | None = None
    edesy_call_id: str | None = None
    created_at: datetime


class CallScheduleFilterParams(BaseModel):
    status: CallScheduleStatus | None = None
    call_purpose: CallPurpose | None = None
