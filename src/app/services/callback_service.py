from datetime import datetime

from app.core.config import settings
from app.core.constants import ActorType, AuditAction, CallPurpose, CallScheduleStatus, RequestedBy
from app.core.exceptions import OutsideBusinessHoursError
from app.models.call_schedule import CallSchedule
from app.services.audit_service import audit_service
from app.services.slot_service import slot_service
from app.utils.datetime_utils import ensure_utc


class CallbackService:
    """Person-requested callback → call_schedules (schema doc §12). Triggered when, during any
    inbound or outbound call, the person asks to be called back at a specific date/time.
    """

    async def create_callback(
        self,
        person_id: str,
        requested_datetime: datetime,
        source_call_id: str,
        appointment_id: str | None = None,
    ) -> CallSchedule:
        requested_datetime = ensure_utc(requested_datetime)
        validity = await slot_service.check_callback_time_valid(requested_datetime)
        if not validity.available:
            raise OutsideBusinessHoursError(validity.reason)

        schedule = CallSchedule(
            person_id=person_id,
            appointment_id=appointment_id,
            scheduled_at=requested_datetime,
            call_purpose=CallPurpose.person_requested_callback,
            requested_by=RequestedBy.person,
            source_call_id=source_call_id,
            status=CallScheduleStatus.pending,
            attempt_number=1,
            max_attempts=settings.default_max_call_attempts,
            created_by=None,
        )
        await schedule.insert()

        await audit_service.record(
            actor_type=ActorType.ai_agent,
            action=AuditAction.create,
            entity_type="call_schedule",
            entity_id=str(schedule.id),
            after=schedule.model_dump(mode="json"),
        )
        return schedule


callback_service = CallbackService()
