from datetime import datetime
from typing import Any

import pymongo
from beanie import Document
from pydantic import Field

from app.core.constants import ActorType, AuditAction
from app.db.base import utcnow


class AuditLog(Document):
    actor_id: str | None = None  # ref admins._id, null if system action
    actor_type: ActorType
    action: AuditAction
    entity_type: str  # "appointment" | "call_schedule" | "person" ...
    entity_id: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "audit_logs"
        indexes = [
            pymongo.IndexModel(
                [
                    ("entity_type", pymongo.ASCENDING),
                    ("entity_id", pymongo.ASCENDING),
                    ("created_at", pymongo.DESCENDING),
                ]
            ),
            pymongo.IndexModel([("actor_id", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)]),
        ]
