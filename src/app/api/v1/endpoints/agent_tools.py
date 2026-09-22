"""The functions Edesy's agent invokes *while on the call* (folder-structure doc). Secured by
`core.tool_auth.require_tool_secret` — a shared secret, not an admin JWT, since Edesy's servers
call these directly with no admin session in play.

`identify_person` is one addition beyond the folder-structure doc's original four tools
(`check_slot_availability`, `book_appointment`, `reschedule_appointment`,
`log_callback_request`): the documented inbound-call flow requires the agent to identify the
caller and learn whether they already have an appointment (PDF §2.1) before it can decide which
branch to take, and no other tool covers that — so it's a necessary part of the documented
architecture, not an invented feature.
"""

from datetime import date, datetime
from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends
from pydantic import BaseModel, BeforeValidator

from app.core.constants import BookingSource
from app.core.exceptions import AppError
from app.core.tool_auth import require_tool_secret
from app.repositories.person_repository import person_repository
from app.schemas.call import ToolResponse
from app.services.appointment_service import appointment_service
from app.services.callback_service import callback_service
from app.services.slot_service import slot_service
from app.utils.datetime_utils import format_ist_human, format_ist_time
from app.utils.validators import is_unresolved_placeholder, strip_unresolved_placeholder

router = APIRouter(
    prefix="/agent-tools", tags=["agent_tools"], dependencies=[Depends(require_tool_secret)]
)


def _reject_unresolved(value: str) -> str:
    """For *required* fields, where silently dropping the value isn't an option — a literal
    `{{call.phone_number}}` must fail loudly (422) rather than get used as a real phone number and
    create a junk Person, which is exactly what makes these bugs invisible until someone notices
    corrupted data days later.
    """
    if is_unresolved_placeholder(value):
        raise ValueError(
            "received an unresolved template token instead of a value — check this tool's "
            "Request Body mapping in the Edesy dashboard"
        )
    return value


# Every optional free-text/id field an Edesy Custom Function can send. Edesy posts unfilled
# optional parameters as the literal token (see utils/validators.py), so each one is normalised
# back to None at the boundary — before any of it can reach a database write.
OptionalToolStr = Annotated[str | None, BeforeValidator(strip_unresolved_placeholder)]
RequiredToolStr = Annotated[str, BeforeValidator(_reject_unresolved)]


class IdentifyPersonRequest(BaseModel):
    phone_number: RequiredToolStr
    full_name: OptionalToolStr = None


@router.post("/identify-person", response_model=ToolResponse)
async def identify_person(payload: IdentifyPersonRequest) -> ToolResponse:
    person = await person_repository.get_or_create_by_phone(payload.phone_number, payload.full_name)
    active_appointment = await appointment_service.get_active_for_person(str(person.id))

    return ToolResponse(
        success=True,
        data={
            "person_id": str(person.id),
            "full_name": person.full_name,
            "has_active_appointment": active_appointment is not None,
            "appointment_id": str(active_appointment.id) if active_appointment else None,
            "appointment_datetime": (
                active_appointment.appointment_datetime.isoformat() if active_appointment else None
            ),
            # Speak this — pre-formatted in India Standard Time, the business's operating zone.
            "appointment_datetime_ist": (
                format_ist_human(active_appointment.appointment_datetime) if active_appointment else None
            ),
        },
    )


class CheckSlotRequest(BaseModel):
    requested_datetime: datetime
    exclude_appointment_id: OptionalToolStr = None


@router.post("/check-slot-availability", response_model=ToolResponse)
async def check_slot_availability(payload: CheckSlotRequest) -> ToolResponse:
    result = await slot_service.check_availability(
        payload.requested_datetime, exclude_appointment_id=payload.exclude_appointment_id
    )
    return ToolResponse(
        success=True,
        data={
            "available": result.available,
            "reason": result.reason,
            "requested_datetime_ist": format_ist_human(payload.requested_datetime),
            # So a "Business is closed on Fridays" rejection can be answered with the days that
            # ARE open, instead of the agent guessing them from its prompt.
            "working_days": await slot_service.get_working_days(),
        },
    )


class ListAvailableSlotsRequest(BaseModel):
    date: date  # "2026-09-22" — the calendar date the caller is interested in


@router.post("/list-available-slots", response_model=ToolResponse)
async def list_available_slots(payload: ListAvailableSlotsRequest) -> ToolResponse:
    """Every real, currently-open slot on a given date — generated from business_config and
    filtered against actual bookings, live. Use this to offer the caller real alternative times
    (e.g. when their first preference is unavailable) instead of guessing — never state a time is
    open without it appearing in this list or having just passed check_slot_availability.

    When count is 0, `is_working_day` says which of the two very different situations it is: a
    day the business is shut (`false` — tell the caller that, and which days `working_days`
    says are open) versus an open day that's fully booked (`true`).
    """
    day = await slot_service.describe_day(payload.date)
    return ToolResponse(
        success=True,
        data={
            "date": payload.date.isoformat(),
            "count": len(day.slots),
            "slots": [
                {"datetime": s.isoformat(), "time_ist": format_ist_time(s)} for s in day.slots
            ],
            "is_working_day": day.is_working_day,
            "closed_reason": day.closed_reason,
            "working_days": day.working_days,
        },
    )


class BookAppointmentRequest(BaseModel):
    # Resolved server-side from Edesy's own call-context variable ({{call.phone_number}}), not
    # taken as an LLM-supplied parameter — a model can and does mis-remember/hallucinate an
    # opaque person_id across turns (observed 2026-09-21: a call booked with person_id="none"
    # because the agent's prompt never called identify_person). The phone number is the one
    # value Edesy resolves live from the call itself, so resolving the Person from it here
    # guarantees every appointment has a real person_id regardless of what the prompt does.
    phone_number: RequiredToolStr
    requested_datetime: datetime
    # No call_id field here on purpose — our internal calls._id doesn't exist yet at this point
    # (that document is only created when the call.ended webhook arrives, after the call is
    # already over), so there was never a real value an agent could supply for it. It was
    # observed sending "none", made-up placeholders, or Edesy's own call id (the wrong id
    # entirely).
    #
    # edesy_call_id is different: it's Edesy's own call-context variable ({{call.sid}}),
    # resolved live by Edesy's platform, not guessed by the LLM — so it's exact and globally
    # unique per call even when the same person has two calls at once. call_service.py uses it
    # for an exact-match correlation once the call.ended webhook creates the real Call document,
    # falling back to a person+timing heuristic only when this wasn't provided (e.g. an older
    # dashboard config, or the prompt genuinely doesn't have it).
    edesy_call_id: OptionalToolStr = None
    # If the caller states/confirms their name during this call (e.g. a call that was scheduled
    # with only a phone number), pass it here so it actually reaches the Person record — the
    # same update-if-different logic identify_person already uses. Optional: omitted or None
    # leaves the existing name untouched.
    full_name: OptionalToolStr = None


@router.post("/book-appointment", response_model=ToolResponse)
async def book_appointment(payload: BookAppointmentRequest) -> ToolResponse:
    person = await person_repository.get_or_create_by_phone(payload.phone_number, payload.full_name)
    try:
        appointment = await appointment_service.book_first_time(
            person_id=str(person.id),
            appointment_datetime=payload.requested_datetime,
            booking_source=BookingSource.inbound_call,
            pending_edesy_call_id=payload.edesy_call_id,
        )
    except AppError as exc:
        return ToolResponse(success=False, message=exc.message)

    return ToolResponse(
        success=True,
        data={
            "appointment_id": str(appointment.id),
            "appointment_datetime": appointment.appointment_datetime.isoformat(),
            "appointment_datetime_ist": format_ist_human(appointment.appointment_datetime),
            "status": appointment.status.value,
        },
    )


class RescheduleAppointmentRequest(BaseModel):
    # Same reasoning as BookAppointmentRequest.phone_number — resolved from Edesy's call context,
    # not trusted from the LLM. appointment_id is still accepted (from identify_person's result,
    # if the prompt calls it) but is optional: if missing or stale, we fall back to the person's
    # current active appointment looked up server-side, so a reschedule still succeeds correctly
    # even when the model never captured a valid appointment_id.
    phone_number: RequiredToolStr
    new_appointment_datetime: datetime
    appointment_id: OptionalToolStr = None
    edesy_call_id: OptionalToolStr = None  # same reasoning as BookAppointmentRequest.edesy_call_id
    full_name: OptionalToolStr = None  # same reasoning as BookAppointmentRequest.full_name


@router.post("/reschedule-appointment", response_model=ToolResponse)
async def reschedule_appointment(payload: RescheduleAppointmentRequest) -> ToolResponse:
    person = await person_repository.get_or_create_by_phone(payload.phone_number, payload.full_name)

    appointment_id = payload.appointment_id
    if not appointment_id or not PydanticObjectId.is_valid(appointment_id):
        active = await appointment_service.get_active_for_person(str(person.id))
        if active is None:
            return ToolResponse(success=False, message="No active appointment found to reschedule")
        appointment_id = str(active.id)

    try:
        appointment = await appointment_service.reschedule_existing(
            appointment_id=appointment_id,
            new_appointment_datetime=payload.new_appointment_datetime,
            pending_edesy_call_id=payload.edesy_call_id,
        )
    except AppError as exc:
        return ToolResponse(success=False, message=exc.message)

    return ToolResponse(
        success=True,
        data={
            "appointment_id": str(appointment.id),
            "appointment_datetime": appointment.appointment_datetime.isoformat(),
            "appointment_datetime_ist": format_ist_human(appointment.appointment_datetime),
            "status": appointment.status.value,
        },
    )


class CancelAppointmentRequest(BaseModel):
    # Same reasoning as RescheduleAppointmentRequest — phone_number resolved from call context;
    # appointment_id is optional and falls back to the person's real active appointment
    # server-side, so the agent can never cancel a wrong or nonexistent appointment based on a
    # misremembered date the caller stated (observed 2026-09-22: a caller said "24 September"
    # when their real appointment was on the 26th — trusting that date directly would have either
    # cancelled nothing or, worse, silently done nothing while claiming success).
    phone_number: RequiredToolStr
    appointment_id: OptionalToolStr = None
    reason: OptionalToolStr = None


@router.post("/cancel-appointment", response_model=ToolResponse)
async def cancel_appointment(payload: CancelAppointmentRequest) -> ToolResponse:
    person = await person_repository.get_or_create_by_phone(payload.phone_number)

    appointment_id = payload.appointment_id
    if not appointment_id or not PydanticObjectId.is_valid(appointment_id):
        active = await appointment_service.get_active_for_person(str(person.id))
        if active is None:
            return ToolResponse(success=False, message="No active appointment found to cancel")
        appointment_id = str(active.id)

    try:
        appointment = await appointment_service.cancel(appointment_id, reason=payload.reason)
    except AppError as exc:
        return ToolResponse(success=False, message=exc.message)

    return ToolResponse(
        success=True,
        data={
            "appointment_id": str(appointment.id),
            "appointment_datetime": appointment.appointment_datetime.isoformat(),
            "appointment_datetime_ist": format_ist_human(appointment.appointment_datetime),
            "status": appointment.status.value,
        },
    )


class LogCallbackRequest(BaseModel):
    # Same reasoning as BookAppointmentRequest.phone_number — resolved from Edesy's call context,
    # not trusted from the LLM.
    phone_number: RequiredToolStr
    requested_datetime: datetime
    # Optional — the agent has no way to know our internal calls._id mid-conversation (that
    # document doesn't exist until the call.ended webhook arrives, after the call is already
    # over; see integrations/edesy/webhook_events.py). Was required before 2026-09-17, which made
    # this tool impossible for the agent to ever call successfully — kept here only in case Vani
    # exposes its own call reference to the agent, purely informational if provided.
    source_call_id: OptionalToolStr = None
    appointment_id: OptionalToolStr = None
    full_name: OptionalToolStr = None  # same reasoning as BookAppointmentRequest.full_name


@router.post("/log-callback-request", response_model=ToolResponse)
async def log_callback_request(payload: LogCallbackRequest) -> ToolResponse:
    person = await person_repository.get_or_create_by_phone(payload.phone_number, payload.full_name)
    try:
        schedule = await callback_service.create_callback(
            person_id=str(person.id),
            requested_datetime=payload.requested_datetime,
            source_call_id=payload.source_call_id,
            appointment_id=payload.appointment_id,
        )
    except AppError as exc:
        return ToolResponse(success=False, message=exc.message)

    return ToolResponse(
        success=True,
        data={
            "call_schedule_id": str(schedule.id),
            "scheduled_at": schedule.scheduled_at.isoformat(),
            "scheduled_at_ist": format_ist_human(schedule.scheduled_at),
        },
    )
