from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_admin, get_page_params
from app.core.constants import CallPurpose, CallScheduleStatus
from app.core.exceptions import NotFoundError
from app.models.admin import Admin
from app.models.call_schedule import CallSchedule
from app.repositories.call_schedule_repository import call_schedule_repository
from app.schemas.call_schedule import CallScheduleCreate, CallScheduleOut
from app.schemas.common import Page, PageParams
from app.services.call_schedule_service import call_schedule_service
from app.utils.pagination import build_page

router = APIRouter(prefix="/call-schedules", tags=["call_schedules"])


def _to_out(schedule: CallSchedule) -> CallScheduleOut:
    return CallScheduleOut(
        id=str(schedule.id),
        person_id=schedule.person_id,
        appointment_id=schedule.appointment_id,
        scheduled_at=schedule.scheduled_at,
        call_purpose=schedule.call_purpose,
        requested_by=schedule.requested_by,
        source_call_id=schedule.source_call_id,
        admin_instructions=schedule.admin_instructions,
        status=schedule.status,
        attempt_number=schedule.attempt_number,
        max_attempts=schedule.max_attempts,
        parent_schedule_id=schedule.parent_schedule_id,
        created_by=schedule.created_by,
        edesy_call_id=schedule.edesy_call_id,
        created_at=schedule.created_at,
    )


@router.get("", response_model=Page[CallScheduleOut])
async def list_call_schedules(
    status: CallScheduleStatus | None = Query(default=None),
    call_purpose: CallPurpose | None = Query(default=None),
    page: PageParams = Depends(get_page_params),
    _: Admin = Depends(get_current_admin),
) -> Page[CallScheduleOut]:
    """The outbound calling queue view (pending/completed/missed) — PDF §3."""
    items, total = await call_schedule_repository.list_filtered(page, status=status, call_purpose=call_purpose)
    return build_page([_to_out(s) for s in items], total, page)


@router.get("/{schedule_id}", response_model=CallScheduleOut)
async def get_call_schedule(schedule_id: str, _: Admin = Depends(get_current_admin)) -> CallScheduleOut:
    schedule = await call_schedule_repository.get_by_id(schedule_id)
    if schedule is None:
        raise NotFoundError("Call schedule not found")
    return _to_out(schedule)


@router.post("", response_model=CallScheduleOut, status_code=201)
async def create_call_schedule(
    payload: CallScheduleCreate, current: Admin = Depends(get_current_admin)
) -> CallScheduleOut:
    schedule = await call_schedule_service.create_admin_scheduled(
        person_id=payload.person_id,
        scheduled_at=payload.scheduled_at,
        admin_id=str(current.id),
        appointment_id=payload.appointment_id,
        admin_instructions=payload.admin_instructions,
    )
    return _to_out(schedule)


@router.post("/{schedule_id}/cancel", response_model=CallScheduleOut)
async def cancel_call_schedule(schedule_id: str, current: Admin = Depends(get_current_admin)) -> CallScheduleOut:
    schedule = await call_schedule_service.cancel(schedule_id, admin_id=str(current.id))
    return _to_out(schedule)
