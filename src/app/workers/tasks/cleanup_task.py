"""Archival for old calls & call_schedules (schema doc §10: "consider a TTL or archival job ...
once volume is confirmed"). Moves terminal-state records older than
settings.archive_after_days into `calls_archive` / `call_schedules_archive` collections, then
deletes them from the primary collection — keeps the hot collections small without discarding the
admin audit trail.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.core.logging import get_logger
from app.db.mongodb import close_db, connect_db, get_database
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

CALLS_TERMINAL_STATUSES = ["answered", "missed", "failed", "busy", "no_answer"]
SCHEDULES_TERMINAL_STATUSES = ["completed", "missed", "cancelled"]


async def _archive_collection(source_name: str, archive_name: str, terminal_statuses: list[str], status_field: str, cutoff: datetime) -> int:
    db = get_database()
    source = db[source_name]
    archive = db[archive_name]

    query = {
        "created_at": {"$lt": cutoff},
        status_field: {"$in": terminal_statuses},
    }

    moved = 0
    cursor = source.find(query)
    async for doc in cursor:
        await archive.insert_one(doc)
        await source.delete_one({"_id": doc["_id"]})
        moved += 1

    return moved


async def _archive_old_records() -> dict[str, int]:
    await connect_db()
    try:
        cutoff = datetime.now(UTC) - timedelta(days=settings.archive_after_days)
        calls_moved = await _archive_collection(
            "calls", "calls_archive", CALLS_TERMINAL_STATUSES, "call_status", cutoff
        )
        schedules_moved = await _archive_collection(
            "call_schedules", "call_schedules_archive", SCHEDULES_TERMINAL_STATUSES, "status", cutoff
        )
        logger.info("cleanup_task_completed", calls_moved=calls_moved, schedules_moved=schedules_moved)
        return {"calls_moved": calls_moved, "call_schedules_moved": schedules_moved}
    finally:
        await close_db()


@celery_app.task(name="app.workers.tasks.cleanup_task.archive_old_records")
def archive_old_records() -> dict[str, int]:
    return asyncio.run(_archive_old_records())
