from datetime import datetime

from beanie import Indexed

from app.core.constants import AdminRole
from app.db.base import TimestampedDocument


class Admin(TimestampedDocument):
    name: str
    email: Indexed(str, unique=True)
    phone_number: str | None = None
    password_hash: str  # bcrypt hash — never store plaintext
    role: AdminRole = AdminRole.admin
    is_active: bool = True
    last_login_at: datetime | None = None

    class Settings(TimestampedDocument.Settings):
        name = "admins"
