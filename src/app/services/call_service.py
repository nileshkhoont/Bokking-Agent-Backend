from app.core.constants import (
    EDESY_FAILURE_REASON_TO_CALL_STATUS,
    CallScheduleStatus,
    CallStatus,
    CallType,
    Direction,
)
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.integrations.edesy.webhook_events import (
    CallEndedEvent,
    CallFailedEvent,
    CallStartedEvent,
    FunctionCalledEvent,
)
from app.models.call import Call, FunctionCallRecord
from app.repositories.call_repository import call_repository
from app.repositories.call_schedule_repository import call_schedule_repository
from app.repositories.person_repository import person_repository
from app.services.missed_call_retry_service import missed_call_retry_service

logger = get_logger(__name__)


class CallService:
    """Call lifecycle + outcome recording, driven entirely by Edesy's signed webhook events
    (folder-structure doc: api/v1/endpoints/webhooks.py dispatches into these handlers).
    """

    async def handle_call_started(self, event: CallStartedEvent) -> Call:
        call_schedule_id = event.context.get("call_schedule_id")
        schedule = None
        if call_schedule_id:
            schedule = await call_schedule_repository.get_by_id(call_schedule_id)

        if schedule:
            person_id = schedule.person_id
            appointment_id = schedule.appointment_id
            call_type = (
                CallType.outbound_missed_retry
                if schedule.call_purpose.value == "missed_call_retry"
                else CallType.outbound_admin_scheduled
            )
            direction = Direction.outbound

            schedule.status = CallScheduleStatus.in_progress
            schedule.edesy_call_id = event.callId
            await schedule.save()
        else:
            # Inbound call — no pre-existing call_schedules row. Identify (or create a
            # placeholder) person by caller phone number; the agent's identify_person tool call
            # will fill in the real name during the conversation.
            person = await person_repository.get_or_create_by_phone(event.phoneNumber)
            person_id = str(person.id)
            appointment_id = None
            call_type = CallType.inbound
            direction = Direction.inbound
            call_schedule_id = None

        call = Call(
            call_schedule_id=call_schedule_id,
            person_id=person_id,
            appointment_id=appointment_id,
            call_type=call_type,
            direction=direction,
            call_status=CallStatus.answered,
            start_time=event.startedAt,
            edesy_call_id=event.callId,
        )
        await call.insert()
        logger.info("call_started", call_id=str(call.id), edesy_call_id=event.callId, call_type=call_type)
        return call

    async def handle_call_ended(self, event: CallEndedEvent) -> Call:
        call = await call_repository.get_by_edesy_call_id(event.callId)
        if call is None:
            raise NotFoundError(f"No call record found for edesy_call_id={event.callId}")

        call.end_time = event.endedAt
        call.duration_seconds = event.durationSeconds
        call.recording_url = event.recordingUrl
        if event.transcript:
            call.transcript_summary = event.transcript.summary
            call.transcript = "\n".join(f"{t.role}: {t.content}" for t in event.transcript.turns)
        await call.save()

        if call.call_schedule_id:
            schedule = await call_schedule_repository.get_by_id(call.call_schedule_id)
            if schedule:
                schedule.status = CallScheduleStatus.completed
                await schedule.save()

        logger.info("call_ended", call_id=str(call.id), edesy_call_id=event.callId)
        return call

    async def handle_call_failed(self, event: CallFailedEvent) -> Call:
        call = await call_repository.get_by_edesy_call_id(event.callId)
        if call is None:
            raise NotFoundError(f"No call record found for edesy_call_id={event.callId}")

        call.call_status = EDESY_FAILURE_REASON_TO_CALL_STATUS.get(
            event.failureReason, CallStatus.failed
        )
        call.end_time = event.failedAt
        await call.save()

        retry = await missed_call_retry_service.handle_failed_call(call)
        logger.info(
            "call_failed",
            call_id=str(call.id),
            edesy_call_id=event.callId,
            failure_reason=event.failureReason,
            retry_scheduled=bool(retry),
        )
        return call

    async def record_function_call(self, event: FunctionCalledEvent) -> Call | None:
        call = await call_repository.get_by_edesy_call_id(event.callId)
        if call is None:
            logger.warning("function_call_event_no_call", edesy_call_id=event.callId, function=event.functionName)
            return None

        call.function_calls.append(
            FunctionCallRecord(
                name=event.functionName,
                arguments=event.arguments,
                result=event.result,
                called_at=event.calledAt,
            )
        )
        await call.save()
        return call


call_service = CallService()
