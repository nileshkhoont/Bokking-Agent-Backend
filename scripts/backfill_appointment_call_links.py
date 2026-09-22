"""One-off data repair: fixes Appointment.created_by_call_id values written before
services/call_service.py's post-call backfill existed. agent_tools.py used to trust an
LLM-supplied call_id for this field, but the real calls._id doesn't exist until after the call
ends — so every value ever written that way was either "none", a made-up placeholder, or Edesy's
own call id (the wrong id entirely).

For each appointment with a missing or garbage (not-a-valid-ObjectId) created_by_call_id, this
looks for a call by the same person whose start/end window contains the appointment's created_at
— the same correlation call_service.py now applies automatically to every new call going
forward — and links it. If no matching call exists (e.g. an admin created it directly, not
during any call), a garbage value is cleared to null rather than left wrong; nothing else changes.

Safe to re-run.

Usage: python scripts/backfill_appointment_call_links.py [--apply]
(dry-run by default — prints what it would change; pass --apply to actually write)
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from beanie import PydanticObjectId  # noqa: E402

from app.db.mongodb import close_db, connect_db  # noqa: E402
from app.models.appointment import Appointment  # noqa: E402
from app.models.call import Call  # noqa: E402
from app.services.call_service import _LINK_WINDOW_SLACK  # noqa: E402


async def main() -> None:
    apply_changes = "--apply" in sys.argv

    await connect_db()
    try:
        appointments = await Appointment.find(Appointment.is_deleted == False).to_list()  # noqa: E712

        linked = 0
        cleared_only = 0
        for appointment in appointments:
            value = appointment.created_by_call_id
            is_garbage = value is not None and not PydanticObjectId.is_valid(value)
            if value is not None and not is_garbage:
                continue  # already a real, valid link — leave it alone

            calls = await Call.find(
                Call.person_id == appointment.person_id, Call.is_deleted == False  # noqa: E712
            ).to_list()
            match = next(
                (
                    c
                    for c in calls
                    if c.start_time
                    and c.end_time
                    and c.start_time - _LINK_WINDOW_SLACK <= appointment.created_at <= c.end_time + _LINK_WINDOW_SLACK
                ),
                None,
            )

            if match:
                print(f"  link appointment {appointment.id} (was {value!r}) -> call {match.id}")
                linked += 1
                if apply_changes:
                    appointment.created_by_call_id = str(match.id)
                    await appointment.save()
            elif is_garbage:
                print(f"  clear garbage created_by_call_id={value!r} on appointment {appointment.id}")
                cleared_only += 1
                if apply_changes:
                    appointment.created_by_call_id = None
                    await appointment.save()

        print()
        print(f"Appointments {'linked' if apply_changes else 'linkable'} to a real call: {linked}")
        print(f"Garbage values {'cleared' if apply_changes else 'to clear'} (no matching call found): {cleared_only}")
        if not apply_changes:
            print("\nDry run only — re-run with --apply to write these changes.")
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
