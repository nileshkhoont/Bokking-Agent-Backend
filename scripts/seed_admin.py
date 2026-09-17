"""Standalone script: creates the first super_admin account so the JWT login flow (POST
/api/v1/auth/login) is usable at all. Not part of the folder-structure doc's original scripts
list, but a necessary addition — there is no other way to obtain the first admin session,
since every admin-facing endpoint requires one to already exist.

Usage:
    python scripts/seed_admin.py --email admin@example.com --password "change-me-now" --name "Admin"

Refuses to run if any admin already exists, unless --force is passed.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.core.constants import AdminRole  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.mongodb import close_db, connect_db  # noqa: E402
from app.models.admin import Admin  # noqa: E402


async def main(email: str, password: str, name: str, force: bool) -> None:
    await connect_db()
    try:
        existing_count = await Admin.find(Admin.is_deleted == False).count()  # noqa: E712
        if existing_count > 0 and not force:
            print(
                f"{existing_count} admin(s) already exist — refusing to seed another super_admin "
                "without --force."
            )
            return

        admin = Admin(
            name=name,
            email=email.lower(),
            password_hash=hash_password(password),
            role=AdminRole.super_admin,
        )
        await admin.insert()
        print(f"Created super_admin: {admin.email} (id={admin.id})")
    finally:
        await close_db()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--name", default="Admin")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    asyncio.run(main(args.email, args.password, args.name, args.force))
