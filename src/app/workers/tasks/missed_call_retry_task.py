"""Safety-net sweep for call_schedules stuck `in_progress` past a reasonable window — catches the
case where Edesy's webhook delivery for a placed call never arrived at all (delivery failure,
dropped event, ...). Stuck entries are simply marked `missed`; nothing is retried automatically —
an admin (or the person themselves, via a callback request) has to schedule a new call.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from app.core.constants import CallScheduleStatus
from app.core.logging import get_logger
from app.db.mongodb import close_db, connect_db
from app.repositories.call_schedule_repository import call_schedule_repository
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

STUCK_THRESHOLD_MINUTES = 45


async def sweep_stuck_schedules_once() -> int:
    """Core sweep logic — assumes the DB is already connected. Shared by the standalone Celery
    task below and by workers/inprocess_scheduler.py.
    """
    swept = 0
    cutoff = datetime.now(UTC) - timedelta(minutes=STUCK_THRESHOLD_MINUTES)
    stuck = await call_schedule_repository.list_stuck_in_progress(cutoff)
    for schedule in stuck:
        schedule.status = CallScheduleStatus.missed
        await schedule.save()
        swept += 1
        logger.warning("stuck_call_schedule_swept", schedule_id=str(schedule.id))
    return swept


async def _sweep_stuck_schedules() -> int:
    await connect_db()
    try:
        return await sweep_stuck_schedules_once()
    finally:
        await close_db()


@celery_app.task(name="app.workers.tasks.missed_call_retry_task.sweep_stuck_schedules")
def sweep_stuck_schedules() -> int:
    return asyncio.run(_sweep_stuck_schedules())
