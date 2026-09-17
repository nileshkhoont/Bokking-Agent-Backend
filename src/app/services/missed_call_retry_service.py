from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.core.constants import ActorType, AuditAction, CallPurpose, CallScheduleStatus, RequestedBy
from app.core.logging import get_logger
from app.models.call import Call
from app.models.call_schedule import CallSchedule
from app.repositories.call_schedule_repository import call_schedule_repository
from app.services.audit_service import audit_service

logger = get_logger(__name__)


class MissedCallRetryService:
    """Auto re-schedule on call.failed (busy/no-answer/rejected/…) — folder-structure doc §0.

    Only applies to outbound calls that originated from a call_schedules entry: an inbound call
    that dropped mid-conversation isn't something we can "retry" — the person is the one who
    called us and can call back.
    """

    async def handle_failed_call(self, call: Call) -> CallSchedule | None:
        if not call.call_schedule_id:
            return None

        parent = await call_schedule_repository.get_by_id(call.call_schedule_id)
        if parent is None:
            logger.warning("missed_call_retry_parent_not_found", call_schedule_id=call.call_schedule_id)
            return None

        return await self._create_retry(parent)

    async def handle_stuck_schedule(self, parent: CallSchedule) -> CallSchedule | None:
        """Safety-net path for workers/tasks/missed_call_retry_task.py: a schedule that was
        marked in_progress by outbound_call_task but never received a call.ended/call.failed
        webhook within a reasonable window (Edesy webhook delivery failure, dropped event, etc.)
        — treated the same as an explicit call.failed.
        """
        return await self._create_retry(parent)

    async def _create_retry(self, parent: CallSchedule) -> CallSchedule | None:
        parent.status = CallScheduleStatus.missed
        await parent.save()

        next_attempt = parent.attempt_number + 1
        if next_attempt > parent.max_attempts:
            logger.info(
                "missed_call_retry_exhausted",
                call_schedule_id=str(parent.id),
                attempts=parent.attempt_number,
                max_attempts=parent.max_attempts,
            )
            return None

        retry = CallSchedule(
            person_id=parent.person_id,
            appointment_id=parent.appointment_id,
            scheduled_at=datetime.now(UTC)
            + timedelta(minutes=settings.missed_call_retry_delay_minutes),
            call_purpose=CallPurpose.missed_call_retry,
            requested_by=RequestedBy.system,
            admin_instructions=parent.admin_instructions,
            status=CallScheduleStatus.pending,
            attempt_number=next_attempt,
            max_attempts=parent.max_attempts,
            parent_schedule_id=str(parent.id),
            created_by=None,
        )
        await retry.insert()

        await audit_service.record(
            actor_type=ActorType.system,
            action=AuditAction.create,
            entity_type="call_schedule",
            entity_id=str(retry.id),
            after=retry.model_dump(mode="json"),
        )
        return retry


missed_call_retry_service = MissedCallRetryService()
