from datetime import datetime

import pymongo

from app.core.constants import CallOutcome, CallStatus, CallType, Direction
from app.db.base import TimestampedDocument


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
    # Pointer to blob storage — not stored in Mongo. Not present in the one real call.ended
    # payload captured so far (2026-09-17); field name/location unconfirmed until a call with an
    # actual recording is observed.
    recording_url: str | None = None
    # The id Edesy returns when a call is placed/received; used to correlate its webhook events
    # back to this record. (Was `telephony_provider_call_id` in the original schema draft — Edesy
    # is the one and only telephony/voice provider here, so this is renamed for clarity.)
    edesy_call_id: str | None = None
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
