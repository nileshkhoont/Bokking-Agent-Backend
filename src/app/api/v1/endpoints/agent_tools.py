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

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.constants import BookingSource
from app.core.exceptions import AppError
from app.core.tool_auth import require_tool_secret
from app.repositories.person_repository import person_repository
from app.schemas.call import ToolResponse
from app.services.appointment_service import appointment_service
from app.services.callback_service import callback_service
from app.services.slot_service import slot_service
from app.utils.datetime_utils import format_ist_human

router = APIRouter(
    prefix="/agent-tools", tags=["agent_tools"], dependencies=[Depends(require_tool_secret)]
)


class IdentifyPersonRequest(BaseModel):
    phone_number: str
    full_name: str | None = None


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
    exclude_appointment_id: str | None = None


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
        },
    )


class BookAppointmentRequest(BaseModel):
    person_id: str
    requested_datetime: datetime
    call_id: str | None = None  # our internal calls._id for this in-progress call


@router.post("/book-appointment", response_model=ToolResponse)
async def book_appointment(payload: BookAppointmentRequest) -> ToolResponse:
    try:
        appointment = await appointment_service.book_first_time(
            person_id=payload.person_id,
            appointment_datetime=payload.requested_datetime,
            booking_source=BookingSource.inbound_call,
            created_by_call_id=payload.call_id,
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
    appointment_id: str
    new_appointment_datetime: datetime
    call_id: str | None = None


@router.post("/reschedule-appointment", response_model=ToolResponse)
async def reschedule_appointment(payload: RescheduleAppointmentRequest) -> ToolResponse:
    try:
        appointment = await appointment_service.reschedule_existing(
            appointment_id=payload.appointment_id,
            new_appointment_datetime=payload.new_appointment_datetime,
            created_by_call_id=payload.call_id,
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


class LogCallbackRequest(BaseModel):
    person_id: str
    requested_datetime: datetime
    # Optional — the agent has no way to know our internal calls._id mid-conversation (that
    # document doesn't exist until the call.ended webhook arrives, after the call is already
    # over; see integrations/edesy/webhook_events.py). Was required before 2026-09-17, which made
    # this tool impossible for the agent to ever call successfully — kept here only in case Vani
    # exposes its own call reference to the agent, purely informational if provided.
    source_call_id: str | None = None
    appointment_id: str | None = None


@router.post("/log-callback-request", response_model=ToolResponse)
async def log_callback_request(payload: LogCallbackRequest) -> ToolResponse:
    try:
        schedule = await callback_service.create_callback(
            person_id=payload.person_id,
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
