"""Standalone script: connects to MongoDB, lets Beanie create every index declared in
models/*.py Settings.indexes, and applies the $jsonSchema validators. Safe to re-run.

Usage: python scripts/create_indexes.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.db.init_db import apply_schema_validators  # noqa: E402
from app.db.mongodb import close_db, connect_db, get_database  # noqa: E402


async def main() -> None:
    await connect_db()
    try:
        await apply_schema_validators(get_database())
        print("Indexes created and schema validators applied.")
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
