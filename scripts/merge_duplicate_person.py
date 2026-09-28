"""One-off data repair: merges a duplicate Person record into the real one it was accidentally
forked from — the 2026-09-25 incident where the same real phone number (+917600181441, "Harsh")
arrived on one call without its country code ("7600181441"), and an exact-string-match lookup
(before normalize_phone_number existed — see utils/validators.py) treated it as a new person
("Mahesh"), forking one real caller into two Person records.

Reassigns every Call, Appointment, and CallSchedule pointing at the duplicate's person_id to the
canonical person's person_id, then soft-deletes the duplicate (is_deleted=True, deleted_at set) —
mirroring the same soft-delete the admin DELETE /persons/{id} endpoint performs. The canonical
person's own fields (name, phone_number, etc.) are never touched.

This is written for the specific 2026-09-25 Harsh/Mahesh pair (ids hardcoded below) — it is NOT a
general "merge any two persons" tool. Safe to re-run: once merged, the duplicate is soft-deleted,
so a second run finds nothing left to move and exits early.

Usage: python scripts/merge_duplicate_person.py [--apply]
(dry-run by default — prints what it would change; pass --apply to actually write)
"""

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.db.mongodb import close_db, connect_db  # noqa: E402
from app.models.appointment import Appointment  # noqa: E402
from app.models.call import Call  # noqa: E402
from app.models.call_schedule import CallSchedule  # noqa: E402
from app.models.person import Person  # noqa: E402

CANONICAL_PERSON_ID = "6ab0c5c603797df05d8d31bf"  # "Harsh", +917600181441 — the real, long-standing record
DUPLICATE_PERSON_ID = "6ab67a488cc8a130fc5231ab"  # "Mahesh", 7600181441 — same real number, no country code


async def main() -> None:
    apply_changes = "--apply" in sys.argv

    await connect_db()
    try:
        canonical = await Person.get(CANONICAL_PERSON_ID)
        duplicate = await Person.get(DUPLICATE_PERSON_ID)
        if canonical is None or duplicate is None:
            print("One of the two person ids no longer exists — nothing to do.")
            return
        if duplicate.is_deleted:
            print("Duplicate is already soft-deleted — nothing left to move. Safe to stop here.")
            return

        print(f"Canonical: {canonical.id}  {canonical.full_name!r}  {canonical.phone_number}")
        print(f"Duplicate: {duplicate.id}  {duplicate.full_name!r}  {duplicate.phone_number}")
        print()

        moved = 0
        for model, label in (
            (Call, "calls"),
            (Appointment, "appointments"),
            (CallSchedule, "call_schedules"),
        ):
            rows = await model.find(model.person_id == DUPLICATE_PERSON_ID).to_list()
            print(f"{label}: {len(rows)} row(s) to reassign")
            for row in rows:
                print(f"  {row.id}")
                moved += 1
                if apply_changes:
                    await model.find_one(model.id == row.id).update(
                        {"$set": {"person_id": CANONICAL_PERSON_ID}}
                    )

        print()
        print(f"Rows {'reassigned' if apply_changes else 'to reassign'}: {moved}")

        if apply_changes:
            duplicate.is_deleted = True
            duplicate.deleted_at = datetime.now(UTC)
            await duplicate.save()
            print(f"Soft-deleted duplicate person {duplicate.id}")
        else:
            print(f"Would soft-delete duplicate person {duplicate.id}")
            print("\nDry run only — re-run with --apply to write these changes.")
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
