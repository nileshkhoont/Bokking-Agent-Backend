"""Safety-net sweep for calls missing a recording_url. call_service.py already tries to fetch it
synchronously the moment call.ended fires, but that isn't reliable on its own — confirmed live
2026-09-22: a real call's recording only appeared on Edesy's own list endpoint several minutes
after its call.ended webhook had already been processed (upload/transcoding lag on Edesy's side).
This periodically retries for any call still missing one, for a bounded window.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from app.core.constants import CallStatus
from app.core.exceptions import EdesyIntegrationError
from app.core.logging import get_logger
from app.db.mongodb import close_db, connect_db
from app.integrations.edesy.client import edesy_client
from app.models.call import Call
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

# Stop retrying after this long — a call still missing a recording after this either never had
# one (e.g. a very short or failed call) or Edesy's own copy isn't coming; no point polling
# forever on something that will never resolve.
GIVE_UP_AFTER_HOURS = 6


async def backfill_missing_recordings_once() -> int:
    """Core sweep logic — assumes the DB is already connected. Shared by the standalone Celery
    task below and by workers/inprocess_scheduler.py.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=GIVE_UP_AFTER_HOURS)
    missing = await Call.find(
        Call.call_status == CallStatus.answered,
        Call.recording_url == None,  # noqa: E711
        Call.is_deleted == False,  # noqa: E712
        Call.created_at >= cutoff,
    ).to_list()
    if not missing:
        return 0

    try:
        edesy_calls = await edesy_client.list_calls()
    except EdesyIntegrationError:
        logger.warning("recording_backfill_list_calls_failed")
        return 0

    recordings_by_sid = {c.callSid: c.recordingUrl for c in edesy_calls if c.recordingUrl}

    filled = 0
    for call in missing:
        url = recordings_by_sid.get(call.edesy_call_id) if call.edesy_call_id else None
        if url:
            call.recording_url = url
            await call.save()
            filled += 1
            logger.info("recording_backfilled", call_id=str(call.id))
    return filled


async def _backfill_missing_recordings() -> int:
    await connect_db()
    try:
        return await backfill_missing_recordings_once()
    finally:
        await close_db()


@celery_app.task(name="app.workers.tasks.recording_backfill_task.backfill_missing_recordings")
def backfill_missing_recordings() -> int:
    return asyncio.run(_backfill_missing_recordings())
