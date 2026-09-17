from typing import Any

from app.core.constants import ActorType, AuditAction
from app.models.audit_log import AuditLog


class AuditService:
    async def record(
        self,
        actor_type: ActorType,
        action: AuditAction,
        entity_type: str,
        entity_id: str,
        actor_id: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> AuditLog:
        log = AuditLog(
            actor_id=actor_id,
            actor_type=actor_type,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before=before,
            after=after,
        )
        await log.insert()
        return log


audit_service = AuditService()
