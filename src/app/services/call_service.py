from datetime import datetime, timedelta

from app.core.constants import CallOutcome, CallScheduleStatus, CallStatus, CallType, Direction
from app.core.logging import get_logger
from app.integrations.edesy.webhook_events import CallEndedEvent, OutcomeInfo
from app.models.appointment import Appointment
from app.models.call import Call
from app.repositories.call_repository import call_repository
from app.repositories.call_schedule_repository import call_schedule_repository
from app.repositories.person_repository import person_repository

# Slack around the call's own start/end (from Edesy's reported duration) to absorb clock skew
# between Edesy and this server, and the second or two between the tool call and the webhook.
_LINK_WINDOW_SLACK = timedelta(minutes=2)

logger = get_logger(__name__)

# Confirmed-real value: "CALLBACK_SCHEDULED" (2026-09-17 capture). The others are reasonable
# best-effort guesses at Vani's disposition vocabulary, not confirmed — an unmapped disposition
# is logged (edesy_unmapped_disposition) rather than silently miscategorized, so real values can
# be added here as they're observed.
_DISPOSITION_TO_OUTCOME: dict[str, CallOutcome] = {
    "callback_scheduled": CallOutcome.callback_requested,
    "appointment_booked": CallOutcome.appointment_booked,
    "appointment_rescheduled": CallOutcome.appointment_rescheduled,
    "no_action": CallOutcome.no_action_taken,
    "no_action_taken": CallOutcome.no_action_taken,
}

# Likewise unconfirmed beyond "completed" (status) and "USER_REQUEST" (endReason, a successful
# end) — matched case-insensitively against both outcome.status and outcome.endReason. Anything
# that doesn't match falls back to CallStatus.failed with a logged warning rather than being
# silently assumed to be either success or a specific failure type.
_FAILURE_KEYWORDS: dict[str, CallStatus] = {
    "no_answer": CallStatus.no_answer,
    "no-answer": CallStatus.no_answer,
    "noanswer": CallStatus.no_answer,
    "voicemail": CallStatus.no_answer,
    "busy": CallStatus.busy,
    "failed": CallStatus.failed,
    "error": CallStatus.failed,
    "rejected": CallStatus.failed,
    "declined": CallStatus.failed,
}


def _map_call_status(outcome: OutcomeInfo | None) -> CallStatus:
    if outcome is None:
        return CallStatus.answered
    if (outcome.status or "").strip().lower() == "completed":
        return CallStatus.answered
    for candidate in (outcome.status, outcome.endReason):
        if not candidate:
            continue
        key = candidate.strip().lower().replace(" ", "_")
        if key in _FAILURE_KEYWORDS:
            return _FAILURE_KEYWORDS[key]
    logger.warning("edesy_unmapped_call_status", status=outcome.status, end_reason=outcome.endReason)
    return CallStatus.failed


def _map_outcome(outcome: OutcomeInfo | None) -> CallOutcome | None:
    if outcome is None or not outcome.disposition:
        return None
    mapped = _DISPOSITION_TO_OUTCOME.get(outcome.disposition.strip().lower())
    if mapped is None:
        logger.info("edesy_unmapped_disposition", disposition=outcome.disposition)
    return mapped


class CallService:
    """Call lifecycle + outcome recording, driven by Vani's single call.ended webhook (see
    integrations/edesy/webhook_events.py for why call.started/call.failed are no longer assumed
    to exist as separate events). Creates the `calls` document AND finalizes it in one shot, since
    this is the only event we get for a call's entire lifecycle.
    """

    async def handle_call_ended(self, event: CallEndedEvent) -> Call:
        call_sid = event.call.callSid
        call = await call_repository.get_by_edesy_call_id(call_sid)

        # Correlate back to the call_schedules row that dispatched this (outbound), if any —
        # edesy_call_id is set there at dispatch time, independently of this webhook ever arriving.
        schedule = await call_schedule_repository.get_by_edesy_call_id(call_sid)

        call_status = _map_call_status(event.outcome)
        end_time = event.timestamp
        duration = event.call.duration
        start_time = end_time - timedelta(seconds=duration) if end_time and duration is not None else None

        transcript_text = "\n".join(f"{t.speaker}: {t.text}" for t in event.transcript) or None
        transcript_summary = None
        if event.outcome and (event.outcome.disposition or event.outcome.endReason):
            transcript_summary = (
                f"{event.outcome.disposition or 'Unknown outcome'} ({event.outcome.endReason or 'n/a'})"
            )
        outcome = _map_outcome(event.outcome)

        if call is None:
            if schedule:
                person_id = schedule.person_id
                appointment_id = schedule.appointment_id
                call_type = CallType.outbound_admin_scheduled
                direction = Direction.outbound
            else:
                # Inbound — no pre-existing call_schedules row. Identify (or create a placeholder)
                # person by caller phone number.
                phone = event.call.from_number
                if phone:
                    person = await person_repository.get_or_create_by_phone(phone)
                    person_id = str(person.id)
                else:
                    logger.error("edesy_webhook_no_person_identifiable", call_sid=call_sid)
                    person_id = "unknown"
                appointment_id = None
                call_type = CallType.inbound
                direction = Direction.inbound

            call = Call(
                call_schedule_id=str(schedule.id) if schedule else None,
                person_id=person_id,
                appointment_id=appointment_id,
                call_type=call_type,
                direction=direction,
                call_status=call_status,
                start_time=start_time,
                end_time=end_time,
                duration_seconds=duration,
                transcript=transcript_text,
                transcript_summary=transcript_summary,
                edesy_call_id=call_sid,
                outcome=outcome,
            )
            await call.insert()
            logger.info(
                "call_recorded",
                call_id=str(call.id),
                edesy_call_id=call_sid,
                call_type=call_type,
                call_status=call_status,
            )
        else:
            call.call_status = call_status
            call.end_time = end_time
            call.duration_seconds = duration
            if start_time:
                call.start_time = start_time
            call.transcript = transcript_text
            call.transcript_summary = transcript_summary
            call.outcome = outcome
            await call.save()
            logger.info("call_updated", call_id=str(call.id), edesy_call_id=call_sid, call_status=call_status)

        if schedule:
            # No auto-retry on failure/no-answer — a missed schedule just stays missed; an admin
            # (or the person themselves, via a callback request) must schedule a new call.
            schedule.status = (
                CallScheduleStatus.completed if call_status == CallStatus.answered else CallScheduleStatus.missed
            )
            await schedule.save()

        await self._link_appointment_created_during_call(call, start_time, end_time)

        return call

    async def _link_appointment_created_during_call(
        self, call: Call, start_time: datetime | None, end_time: datetime | None
    ) -> None:
        """book_appointment/reschedule_appointment (agent_tools.py) run *during* the live call,
        before this Call document exists — there is no real calls._id an agent could ever supply
        at that point (observed: "none", made-up placeholders, or Edesy's own call id instead of
        ours). Appointment.created_by_call_id is deliberately left unset there and backfilled
        here instead, in two steps:

        1. Exact match on pending_edesy_call_id (Edesy's own callSid, captured at booking time
           from the call-context variable {{call.sid}} — not LLM-supplied, so it's unique per
           call even when the same person has two calls running at once). Tried first because
           it's unambiguous.
        2. Falls back to a person + created-within-this-call's-time-window heuristic, only for
           appointments booked before a dashboard config carries edesy_call_id, or a prompt that
           doesn't send it. That heuristic is safe across *different* people's concurrent calls
           (it's scoped by person_id) but could misattribute if the same person genuinely has two
           overlapping calls — step 1 is what actually closes that gap.
        """
        appointment = None
        if call.edesy_call_id:
            appointment = await Appointment.find_one(
                Appointment.pending_edesy_call_id == call.edesy_call_id,
                Appointment.created_by_call_id == None,  # noqa: E711
                Appointment.is_deleted == False,  # noqa: E712
            )

        if appointment is None and start_time and end_time:
            appointment = (
                await Appointment.find(
                    Appointment.person_id == call.person_id,
                    Appointment.created_by_call_id == None,  # noqa: E711
                    Appointment.created_at >= start_time - _LINK_WINDOW_SLACK,
                    Appointment.created_at <= end_time + _LINK_WINDOW_SLACK,
                    Appointment.is_deleted == False,  # noqa: E712
                )
                .sort(-Appointment.created_at)
                .first_or_none()
            )

        if appointment:
            appointment.created_by_call_id = str(call.id)
            await appointment.save()
            logger.info(
                "appointment_linked_to_call", appointment_id=str(appointment.id), call_id=str(call.id)
            )


call_service = CallService()
