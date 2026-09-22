"""One-off data repair: fetches recording URLs for existing `calls` rows that don't have one —
call_service.py now sets this automatically for every new call going forward, but calls recorded
before that fix has no way to get it retroactively except by asking Edesy directly.

Confirmed live 2026-09-22: `call.ended`'s own webhook payload never includes a recording;
GET /api/v1/calls/{id} (singular) 404s for both callSid and conversationId; the only place a
recording has actually been observed is GET /api/v1/calls (the list endpoint) — matched here by
callSid client-side, since the endpoint's own callSid filter appears to be silently ignored.

Safe to re-run.

Usage: python scripts/backfill_call_recordings.py [--apply] [--limit N]
(dry-run by default — prints what it would change; pass --apply to actually write; --limit
controls how many recent Edesy calls to fetch, default 50 — raise it if you have more history
than that to backfill)
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.db.mongodb import close_db, connect_db  # noqa: E402
from app.integrations.edesy.client import edesy_client  # noqa: E402
from app.models.call import Call  # noqa: E402


async def main() -> None:
    apply_changes = "--apply" in sys.argv
    limit = 50
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    await connect_db()
    try:
        edesy_calls = await edesy_client.list_calls(limit=limit)
        recordings_by_sid = {c.callSid: c.recordingUrl for c in edesy_calls if c.recordingUrl}
        print(f"Fetched {len(edesy_calls)} calls from Edesy, {len(recordings_by_sid)} with a recording.\n")

        calls = await Call.find(
            Call.is_deleted == False, Call.recording_url == None  # noqa: E712,E711
        ).to_list()

        found = 0
        for call in calls:
            if not call.edesy_call_id:
                continue
            url = recordings_by_sid.get(call.edesy_call_id)
            if not url:
                continue
            print(f"  set recording_url on call {call.id} (edesy_call_id={call.edesy_call_id})")
            found += 1
            if apply_changes:
                call.recording_url = url
                await call.save()

        print()
        print(f"Calls missing a recording_url: {len(calls)}")
        print(f"Recordings {'set' if apply_changes else 'found'}: {found}")
        if not apply_changes:
            print("\nDry run only — re-run with --apply to write these changes.")
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
