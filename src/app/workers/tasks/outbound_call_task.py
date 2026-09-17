"""Picks up due call_schedules entries and places the call via Edesy. `place_call` is not
idempotent on Edesy's side, so `call_schedules._id` is passed as the idempotency key
(folder-structure doc's cross-cutting practices table), and a schedule is flipped out of
"pending" before dispatch so the same due entry is never picked up twice by overlapping polls.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.core.constants import CallScheduleStatus
from app.core.exceptions import EdesyIntegrationError
from app.core.logging import get_logger
from app.db.mongodb import close_db, connect_db
from app.integrations.edesy.client import edesy_client
from app.integrations.edesy.prompts import render_admin_instructions_context
from app.models.person import Person
from app.repositories.call_schedule_repository import call_schedule_repository
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


async def dispatch_due_calls_once() -> int:
    """Core dispatch logic — assumes the DB is already connected. Shared by the standalone Celery
    task below and by workers/inprocess_scheduler.py (a Redis/Celery-free dev fallback that runs
    this same logic on a timer inside the API process itself).
    """
    if not settings.edesy_agent_id:
        logger.warning("outbound_call_task_skipped", reason="EDESY_AGENT_ID not configured")
        return 0

    dispatched = 0
    due = await call_schedule_repository.list_due(datetime.now(UTC))
    for schedule in due:
        person = await Person.get(schedule.person_id)
        if person is None or person.is_deleted:
            logger.error("outbound_call_person_missing", schedule_id=str(schedule.id))
            schedule.status = CallScheduleStatus.cancelled
            await schedule.save()
            continue

        # Flip status before dispatching so a concurrent poll can't double-place this call.
        schedule.status = CallScheduleStatus.in_progress
        await schedule.save()

        context = {
            "call_schedule_id": str(schedule.id),
            "person_id": schedule.person_id,
            "appointment_id": schedule.appointment_id,
            "admin_instructions": render_admin_instructions_context(schedule.admin_instructions),
        }

        try:
            result = await edesy_client.place_call(
                agent_id=settings.edesy_agent_id,
                phone_number=person.phone_number,
                context=context,
                idempotency_key=str(schedule.id),
            )
            schedule.edesy_call_id = result.call_id
            await schedule.save()
            dispatched += 1
            logger.info("outbound_call_dispatched", schedule_id=str(schedule.id), edesy_call_id=result.call_id)
        except EdesyIntegrationError as exc:
            logger.error("outbound_call_dispatch_failed", schedule_id=str(schedule.id), error=str(exc))
            # Back off: revert to pending a few minutes out rather than hot-looping every poll.
            schedule.status = CallScheduleStatus.pending
            schedule.scheduled_at = datetime.now(UTC) + timedelta(minutes=5)
            await schedule.save()
    return dispatched


async def _dispatch_due_calls() -> int:
    """Standalone entry point for the Celery task — owns its own DB connection since it runs in
    a separate worker process from the API.
    """
    await connect_db()
    try:
        return await dispatch_due_calls_once()
    finally:
        await close_db()


@celery_app.task(name="app.workers.tasks.outbound_call_task.dispatch_due_calls")
def dispatch_due_calls() -> int:
    return asyncio.run(_dispatch_due_calls())
