from datetime import UTC, datetime

from beanie import Document
from pydantic import Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampedDocument(Document):
    """Base mixin: created_at/updated_at + soft-delete fields shared by every collection,
    per the schema doc's stated design principle (soft deletes to preserve the admin audit trail).
    """

    is_deleted: bool = False
    deleted_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        use_state_management = True
