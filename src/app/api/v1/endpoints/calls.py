from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_admin, get_page_params
from app.core.constants import CallOutcome, CallStatus, CallType
from app.core.exceptions import NotFoundError
from app.models.admin import Admin
from app.models.call import Call
from app.models.person import Person
from app.repositories.call_repository import call_repository
from app.repositories.person_repository import person_repository
from app.schemas.call import CallOut
from app.schemas.common import Page, PageParams
from app.utils.pagination import build_page

router = APIRouter(prefix="/calls", tags=["calls"])


def _to_out(call: Call, person: Person | None = None) -> CallOut:
    return CallOut(
        id=str(call.id),
        call_schedule_id=call.call_schedule_id,
        person_id=call.person_id,
        person_full_name=person.full_name if person else None,
        person_phone_number=person.phone_number if person else None,
        appointment_id=call.appointment_id,
        call_type=call.call_type,
        direction=call.direction,
        call_status=call.call_status,
        start_time=call.start_time,
        end_time=call.end_time,
        duration_seconds=call.duration_seconds,
        transcript=call.transcript,
        transcript_summary=call.transcript_summary,
        recording_url=call.recording_url,
        edesy_call_id=call.edesy_call_id,
        outcome=call.outcome,
        created_at=call.created_at,
    )


@router.get("", response_model=Page[CallOut])
async def list_calls(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    call_type: CallType | None = Query(default=None),
    call_status: CallStatus | None = Query(default=None),
    outcome: CallOutcome | None = Query(default=None),
    person_id: str | None = Query(default=None),
    q: str | None = Query(default=None, description="Search by person name or phone number"),
    page: PageParams = Depends(get_page_params),
    _: Admin = Depends(get_current_admin),
) -> Page[CallOut]:
    """Admin Call Management: date-wise list with type/status/outcome filters (PDF §2.2)."""
    person_ids: list[str] | None = None
    if q:
        person_ids = await person_repository.find_ids_matching(q)
        if not person_ids:
            return build_page([], 0, page)

    items, total = await call_repository.list_filtered(
        page,
        date_from=date_from,
        date_to=date_to,
        call_type=call_type,
        call_status=call_status,
        outcome=outcome,
        person_id=person_id,
        person_ids=person_ids,
    )
    persons = await person_repository.get_many_by_ids({c.person_id for c in items})
    return build_page([_to_out(c, persons.get(c.person_id)) for c in items], total, page)


@router.get("/{call_id}", response_model=CallOut)
async def get_call(call_id: str, _: Admin = Depends(get_current_admin)) -> CallOut:
    call = await call_repository.get_by_id(call_id)
    if call is None:
        raise NotFoundError("Call not found")
    person = await person_repository.get_by_id(call.person_id)
    return _to_out(call, person)
