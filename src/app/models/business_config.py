from datetime import datetime

from beanie import Document
from pydantic import BaseModel, Field

from app.db.base import utcnow


class WorkingHours(BaseModel):
    """One time window within a working day, e.g. {"start": "11:00", "end": "13:30"}. A day can
    have more than one window (e.g. a morning session and a separate evening session) — see
    BusinessConfig.working_hours below.
    """

    start: str | None = None  # "09:00"
    end: str | None = None  # "18:00"


class Holiday(BaseModel):
    date: datetime
    reason: str | None = None


class BusinessConfig(Document):
    """Singleton document — one source of truth for slot availability for the whole business
    (booking is confirmed NOT doctor-wise, so there is no per-doctor config anywhere).
    """

    working_days: list[str] = []  # e.g. ["monday", "tuesday", ...]
    # Same windows apply on every working_days entry — e.g. [{"11:00","13:30"}, {"17:00","18:30"}]
    # for a business that's open mornings and evenings but closed midday.
    working_hours: list[WorkingHours] = []
    slot_duration_minutes: int | None = None
    buffer_minutes: int | None = None
    holidays: list[Holiday] = []
    max_advance_booking_days: int | None = None
    timezone: str | None = None  # e.g. "Asia/Kolkata"
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "business_config"
