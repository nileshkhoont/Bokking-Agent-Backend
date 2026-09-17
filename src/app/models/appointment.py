from datetime import datetime

import pymongo
from beanie import Indexed

from app.core.constants import AppointmentStatus, BookingSource
from app.db.base import TimestampedDocument


class Appointment(TimestampedDocument):
    person_id: Indexed(str)  # ref persons._id
    appointment_datetime: Indexed(datetime)  # combined date+time, stored in UTC
    duration_minutes: int | None = None
    status: AppointmentStatus
    booking_source: BookingSource
    original_appointment_id: str | None = None  # self-ref — reschedule chain
    notes: str | None = None
    created_by_call_id: str | None = None  # ref calls._id — which call resulted in this booking

    class Settings(TimestampedDocument.Settings):
        name = "appointments"
        indexes = [
            pymongo.IndexModel(
                [("person_id", pymongo.ASCENDING), ("appointment_datetime", pymongo.DESCENDING)]
            ),
            pymongo.IndexModel([("status", pymongo.ASCENDING)]),
            # DB-level double-booking guard: only one active (booked/rescheduled) appointment per slot.
            # Booking is confirmed NOT doctor-wise, so this is a single business-wide slot lock.
            pymongo.IndexModel(
                [("appointment_datetime", pymongo.ASCENDING)],
                unique=True,
                partialFilterExpression={"status": {"$in": ["booked", "rescheduled"]}},
            ),
        ]
