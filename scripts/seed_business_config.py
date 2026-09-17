"""Standalone script: creates the singleton business_config document if one doesn't already
exist. The requirements PDF (§8.2) leaves actual working days/hours/slot-duration/holidays as an
OPEN CLIENT QUESTION — this script does not invent real business values. It seeds clearly-labeled
placeholder defaults so the system (which requires business_config to exist for any slot check to
run at all) is usable end-to-end in dev/testing, and prints a loud reminder that an admin must
review/update them via PATCH /api/v1/business-config (settings/business-config in the UI) before
this goes live with real appointment data.

Usage: python scripts/seed_business_config.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.db.mongodb import close_db, connect_db  # noqa: E402
from app.models.business_config import BusinessConfig, WorkingHours  # noqa: E402

PLACEHOLDER_CONFIG = dict(
    working_days=["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"],
    working_hours=WorkingHours(start="09:00", end="18:00"),
    slot_duration_minutes=30,
    buffer_minutes=0,
    holidays=[],
    max_advance_booking_days=30,
    timezone="Asia/Kolkata",
)


async def main() -> None:
    await connect_db()
    try:
        existing = await BusinessConfig.find_one({})
        if existing:
            print("business_config already exists — leaving it as-is. No changes made.")
            return

        config = BusinessConfig(**PLACEHOLDER_CONFIG)
        await config.insert()
        print(
            "Seeded business_config with PLACEHOLDER values (Mon-Sat 09:00-18:00, 30-min slots, "
            "Asia/Kolkata, 30-day advance window).\n"
            "These are NOT confirmed business values — the requirements doc (§8.2) leaves the "
            "real working days/hours/slot duration/holidays as an open client question.\n"
            "Update them via PATCH /api/v1/business-config (or the settings/business-config page) "
            "before relying on this for real appointment booking."
        )
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
