from datetime import datetime

from app.core.constants import ActorType, AuditAction, CallPurpose, CallScheduleStatus, RequestedBy
from app.core.exceptions import NotFoundError
from app.models.call_schedule import CallSchedule
from app.repositories.call_schedule_repository import call_schedule_repository
from app.services.audit_service import audit_service
from app.utils.datetime_utils import ensure_utc


class CallScheduleService:
    """Queue creation for admin-scheduled calls (PDF §3.1): admin picks a person — either from
    their already-booked appointments or via a fresh schedule-call form — sets a date/time, and
    optionally leaves instructions for the agent to discuss.
    """

    async def create_admin_scheduled(
        self,
        person_id: str,
        scheduled_at: datetime,
        admin_id: str,
        appointment_id: str | None = None,
        admin_instructions: str | None = None,
        notes: str | None = None,
    ) -> CallSchedule:
        schedule = CallSchedule(
            person_id=person_id,
            appointment_id=appointment_id,
            scheduled_at=ensure_utc(scheduled_at),
            call_purpose=CallPurpose.admin_scheduled,
            requested_by=RequestedBy.admin,
            admin_instructions=admin_instructions,
            notes=notes,
            status=CallScheduleStatus.pending,
            created_by=admin_id,
        )
        await schedule.insert()
        await audit_service.record(
            actor_type=ActorType.admin,
            action=AuditAction.create,
            entity_type="call_schedule",
            entity_id=str(schedule.id),
            actor_id=admin_id,
            after=schedule.model_dump(mode="json"),
        )
        return schedule

    async def cancel(self, schedule_id: str, admin_id: str | None = None) -> CallSchedule:
        schedule = await call_schedule_repository.get_by_id(schedule_id)
        if schedule is None:
            raise NotFoundError("Call schedule not found")

        before = schedule.model_dump(mode="json")
        schedule.status = CallScheduleStatus.cancelled
        await schedule.save()

        await audit_service.record(
            actor_type=ActorType.admin if admin_id else ActorType.system,
            action=AuditAction.cancel,
            entity_type="call_schedule",
            entity_id=str(schedule.id),
            actor_id=admin_id,
            before=before,
            after=schedule.model_dump(mode="json"),
        )
        return schedule


call_schedule_service = CallScheduleService()
