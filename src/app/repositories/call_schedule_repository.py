from datetime import datetime

from app.core.constants import CallPurpose, CallScheduleStatus
from app.models.call_schedule import CallSchedule
from app.schemas.common import PageParams


class CallScheduleRepository:
    async def get_by_id(self, schedule_id: str) -> CallSchedule | None:
        schedule = await CallSchedule.get(schedule_id)
        if schedule is None or schedule.is_deleted:
            return None
        return schedule

    async def list_due(self, as_of: datetime, limit: int = 50) -> list[CallSchedule]:
        """The outbound queue worker's core read: all pending entries due now — backed by the
        {status, scheduled_at} compound index (schema doc §6).
        """
        return (
            await CallSchedule.find(
                CallSchedule.status == CallScheduleStatus.pending,
                CallSchedule.scheduled_at <= as_of,
                CallSchedule.is_deleted == False,  # noqa: E712
            )
            .sort(+CallSchedule.scheduled_at)
            .limit(limit)
            .to_list()
        )

    async def list_stuck_in_progress(self, older_than: datetime) -> list[CallSchedule]:
        return await CallSchedule.find(
            CallSchedule.status == CallScheduleStatus.in_progress,
            CallSchedule.updated_at <= older_than,
            CallSchedule.is_deleted == False,  # noqa: E712
        ).to_list()

    async def list_filtered(
        self,
        page: PageParams,
        status: CallScheduleStatus | None = None,
        call_purpose: CallPurpose | None = None,
    ) -> tuple[list[CallSchedule], int]:
        conditions: list = [CallSchedule.is_deleted == False]  # noqa: E712
        if status:
            conditions.append(CallSchedule.status == status)
        if call_purpose:
            conditions.append(CallSchedule.call_purpose == call_purpose)

        query = CallSchedule.find(*conditions)
        total = await query.count()
        items = (
            await query.sort(-CallSchedule.scheduled_at)
            .skip(page.skip)
            .limit(page.page_size)
            .to_list()
        )
        return items, total


call_schedule_repository = CallScheduleRepository()
