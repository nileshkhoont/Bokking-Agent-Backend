from fastapi import APIRouter, Depends

from app.api.deps import get_current_admin
from app.core.constants import AppointmentStatus, CallStatus, CallType
from app.models.admin import Admin
from app.models.appointment import Appointment
from app.models.call import Call
from app.models.call_schedule import CallSchedule
from app.schemas.call import DashboardStats

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(_: Admin = Depends(get_current_admin)) -> DashboardStats:
    """Aggregated booked/missed/outcome counts for the admin overview page."""
    booked = await Appointment.find(
        Appointment.is_deleted == False,  # noqa: E712
        {"status": {"$in": [AppointmentStatus.booked.value, AppointmentStatus.rescheduled.value]}},
    ).count()
    cancelled = await Appointment.find(
        Appointment.is_deleted == False, Appointment.status == AppointmentStatus.cancelled  # noqa: E712
    ).count()
    inbound = await Call.find(
        Call.is_deleted == False, Call.call_type == CallType.inbound  # noqa: E712
    ).count()
    outbound = await Call.find(
        Call.is_deleted == False,  # noqa: E712
        {"call_type": {"$in": [CallType.outbound_admin_scheduled.value, CallType.outbound_missed_retry.value]}},
    ).count()
    admin_scheduled = await CallSchedule.find(
        CallSchedule.is_deleted == False, CallSchedule.call_purpose == "admin_scheduled"  # noqa: E712
    ).count()
    agent_scheduled = await CallSchedule.find(
        CallSchedule.is_deleted == False,  # noqa: E712
        {"call_purpose": {"$in": ["missed_call_retry", "person_requested_callback"]}},
    ).count()
    failed = await Call.find(
        Call.is_deleted == False,  # noqa: E712
        {"call_status": {"$in": [CallStatus.failed.value, CallStatus.busy.value, CallStatus.no_answer.value]}},
    ).count()

    return DashboardStats(
        booked_appointments=booked,
        cancelled_appointments=cancelled,
        inbound_calls=inbound,
        outbound_calls=outbound,
        admin_scheduled_calls=admin_scheduled,
        agent_scheduled_calls=agent_scheduled,
        failed_calls=failed,
    )
