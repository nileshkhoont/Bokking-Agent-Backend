"""One-off data repair: appointments booked by the agent during a call WE placed (an
admin-scheduled or callback call) were all saved with booking_source="inbound_call", because
agent_tools.book_appointment hard-coded it regardless of call direction (fixed for new bookings).

An appointment's origin is decided from evidence about how it was originally BOOKED, never
guessed:
  1. created_by_call_id -> a Call that has a call_schedule_id (we dispatched it), or
  2. pending_edesy_call_id -> a call_schedules row with that edesy_call_id.
A reschedule copies booking_source from the appointment it replaces, so a whole reschedule chain
is decided by its ROOT: only when the root was booked on a call we placed do the chain's
"inbound_call" rows become "admin_scheduled_call". A root booked on an inbound call, or with no
evidence either way, is left untouched, as is every row that isn't currently "inbound_call".

Only booking_source is written (a targeted $set — updated_at is not touched). Safe to re-run.

Usage: python scripts/backfill_appointment_booking_source.py [--apply]
(dry-run by default — prints what it would change; pass --apply to actually write)
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from beanie import PydanticObjectId  # noqa: E402

from app.core.constants import BookingSource  # noqa: E402
from app.db.mongodb import close_db, connect_db  # noqa: E402
from app.models.appointment import Appointment  # noqa: E402
from app.models.call import Call  # noqa: E402
from app.models.call_schedule import CallSchedule  # noqa: E402


async def _booked_on_our_call(appointment: Appointment) -> bool | None:
    """True/False when the evidence is conclusive, None when there is none."""
    call_id = appointment.created_by_call_id
    if call_id and PydanticObjectId.is_valid(call_id):
        call = await Call.get(call_id)
        if call is not None:
            return bool(call.call_schedule_id)
    if appointment.pending_edesy_call_id:
        schedule = await CallSchedule.find_one(CallSchedule.edesy_call_id == appointment.pending_edesy_call_id)
        if schedule is not None:
            return True
    return None


async def main() -> None:
    apply_changes = "--apply" in sys.argv

    await connect_db()
    try:
        appointments = await Appointment.find(Appointment.is_deleted == False).to_list()  # noqa: E712
        by_id = {str(a.id): a for a in appointments}

        def root_of(appointment: Appointment) -> Appointment:
            seen = {str(appointment.id)}
            current = appointment
            while current.original_appointment_id and current.original_appointment_id in by_id:
                if current.original_appointment_id in seen:
                    break  # defensive: a cycle must never hang the script
                seen.add(current.original_appointment_id)
                current = by_id[current.original_appointment_id]
            return current

        root_verdict: dict[str, bool | None] = {}
        to_fix: list[Appointment] = []
        undecided = 0
        for appointment in appointments:
            if appointment.booking_source != BookingSource.inbound_call:
                continue
            root = root_of(appointment)
            key = str(root.id)
            if key not in root_verdict:
                root_verdict[key] = await _booked_on_our_call(root)
            verdict = root_verdict[key]
            if verdict is True:
                to_fix.append(appointment)
            elif verdict is None:
                undecided += 1
                print(f"  leave alone (no evidence either way): appointment {appointment.id}")

        for appointment in to_fix:
            print(
                f"  {appointment.id}  {appointment.appointment_datetime:%Y-%m-%d %H:%M}Z  "
                f"{appointment.status.value:<11} inbound_call -> admin_scheduled_call"
            )
            if apply_changes:
                await Appointment.find_one(Appointment.id == appointment.id).update(
                    {"$set": {"booking_source": BookingSource.admin_scheduled_call.value}}
                )

        print()
        print(f"Appointments {'corrected' if apply_changes else 'to correct'}: {len(to_fix)}")
        print(f"Left alone (booked on an inbound call): {sum(1 for a in appointments if a.booking_source == BookingSource.inbound_call) - len(to_fix) - undecided}")
        print(f"Left alone (no evidence either way): {undecided}")
        if not apply_changes:
            print("\nDry run only — re-run with --apply to write these changes.")
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
