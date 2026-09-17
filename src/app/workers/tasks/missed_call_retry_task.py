"""Safety-net sweep for call_schedules stuck `in_progress` past a reasonable window — the primary
missed-call retry trigger is the synchronous `call.failed` webhook handler
(services.missed_call_retry_service.handle_failed_call), not this periodic task. This only
catches the case where Edesy's webhook delivery for a placed call never arrived at all.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from app.core.logging import get_logger
from app.db.mongodb import close_db, connect_db
from app.repositories.call_schedule_repository import call_schedule_repository
from app.services.missed_call_retry_service import missed_call_retry_service
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
        await missed_call_retry_service.handle_stuck_schedule(schedule)
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
