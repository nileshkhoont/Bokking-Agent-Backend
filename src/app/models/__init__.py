from app.models.admin import Admin
from app.models.appointment import Appointment
from app.models.audit_log import AuditLog
from app.models.business_config import BusinessConfig
from app.models.call import Call
from app.models.call_schedule import CallSchedule
from app.models.person import Person

DOCUMENT_MODELS = [
    Admin,
    Person,
    BusinessConfig,
    Appointment,
    CallSchedule,
    Call,
    AuditLog,
]

__all__ = [
    "Admin",
    "Person",
    "BusinessConfig",
    "Appointment",
    "CallSchedule",
    "Call",
    "AuditLog",
    "DOCUMENT_MODELS",
]
