from datetime import datetime
from typing import Any

import pymongo
from pydantic import BaseModel

from app.core.constants import CallOutcome, CallStatus, CallType, Direction
from app.db.base import TimestampedDocument


class FunctionCallRecord(BaseModel):
    """Audit trail of one agent_tools invocation during this call (from the `function.called`
    Edesy webhook event) — lets an admin see exactly which tool the agent invoked and with what
    result.
    """

    name: str
    arguments: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    called_at: datetime | None = None


class Call(TimestampedDocument):
    call_schedule_id: str | None = None  # ref call_schedules._id — null for inbound calls
    person_id: str  # ref persons._id
    appointment_id: str | None = None  # ref appointments._id
    call_type: CallType
    direction: Direction
    call_status: CallStatus
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_seconds: int | None = None
    transcript: str | None = None
    transcript_summary: str | None = None
    recording_url: str | None = None  # pointer to blob storage — not stored in Mongo
    # The id Edesy returns when a call is placed/received; used to correlate its webhook events
    # back to this record. (Was `telephony_provider_call_id` in the original schema draft — Edesy
    # is the one and only telephony/voice provider here, so this is renamed for clarity.)
    edesy_call_id: str | None = None
    function_calls: list[FunctionCallRecord] = []
    outcome: CallOutcome | None = None

    class Settings(TimestampedDocument.Settings):
        name = "calls"
        indexes = [
            pymongo.IndexModel([("person_id", pymongo.ASCENDING), ("start_time", pymongo.DESCENDING)]),
            pymongo.IndexModel([("call_type", pymongo.ASCENDING), ("start_time", pymongo.DESCENDING)]),
            pymongo.IndexModel([("call_status", pymongo.ASCENDING)]),
            pymongo.IndexModel([("appointment_id", pymongo.ASCENDING)]),
            pymongo.IndexModel([("edesy_call_id", pymongo.ASCENDING)], sparse=True),
            # Supports the admin dashboard's date-wise view + status filters in one query
            pymongo.IndexModel(
                [
                    ("start_time", pymongo.DESCENDING),
                    ("call_status", pymongo.ASCENDING),
                    ("call_type", pymongo.ASCENDING),
                ]
            ),
        ]
