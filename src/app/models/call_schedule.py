from datetime import datetime

import pymongo

from app.core.constants import CallPurpose, CallScheduleStatus, RequestedBy
from app.db.base import TimestampedDocument


class CallSchedule(TimestampedDocument):
    person_id: str  # ref persons._id
    appointment_id: str | None = None  # ref appointments._id
    scheduled_at: datetime
    call_purpose: CallPurpose
    requested_by: RequestedBy
    source_call_id: str | None = None  # ref calls._id — person-requested callback origin
    admin_instructions: str | None = None
    status: CallScheduleStatus = CallScheduleStatus.pending
    attempt_number: int = 1
    max_attempts: int = 3
    parent_schedule_id: str | None = None  # self-ref — retry/re-request chain
    created_by: str | None = None  # ref admins._id, null if system/agent-generated
    edesy_call_id: str | None = None  # set once outbound_call_task places the call with Edesy

    class Settings(TimestampedDocument.Settings):
        name = "call_schedules"
        indexes = [
            # Core queue-worker index — "give me all pending calls due now"
            pymongo.IndexModel([("status", pymongo.ASCENDING), ("scheduled_at", pymongo.ASCENDING)]),
            pymongo.IndexModel([("person_id", pymongo.ASCENDING)]),
            pymongo.IndexModel([("parent_schedule_id", pymongo.ASCENDING)]),
            pymongo.IndexModel([("source_call_id", pymongo.ASCENDING)], sparse=True),
        ]
