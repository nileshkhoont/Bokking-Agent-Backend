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
    # Free-text note for the ADMIN's own reference (the dashboard's "Notes" field). Never sent to
    # the AI agent — unlike admin_instructions above, which is fed into the call context.
    notes: str | None = None
    status: CallScheduleStatus = CallScheduleStatus.pending
    created_by: str | None = None  # ref admins._id, null if system/agent-generated
    edesy_call_id: str | None = None  # set once outbound_call_task places the call with Edesy

    class Settings(TimestampedDocument.Settings):
        name = "call_schedules"
        indexes = [
            # Core queue-worker index — "give me all pending calls due now"
            pymongo.IndexModel([("status", pymongo.ASCENDING), ("scheduled_at", pymongo.ASCENDING)]),
            pymongo.IndexModel([("person_id", pymongo.ASCENDING)]),
            pymongo.IndexModel([("source_call_id", pymongo.ASCENDING)], sparse=True),
        ]
