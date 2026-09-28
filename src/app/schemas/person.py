from datetime import datetime

from pydantic import BaseModel, field_validator

from app.models.person import Address
from app.utils.validators import normalize_phone_number


class PersonCreate(BaseModel):
    full_name: str | None = None
    phone_number: str
    alternate_phone: str | None = None
    email: str | None = None
    gender: str | None = None
    date_of_birth: datetime | None = None
    address: Address | None = None
    preferred_language: str | None = None
    notes: str | None = None

    # Normalized here too (not just in person_repository) so an admin typing a bare 10-digit
    # number into this form/API is stored the same way a caller's own number would be — see
    # normalize_phone_number's docstring for the incident this prevents.
    _normalize_phone_number = field_validator("phone_number")(staticmethod(normalize_phone_number))

    @field_validator("alternate_phone")
    @classmethod
    def _normalize_alternate_phone(cls, value: str | None) -> str | None:
        return normalize_phone_number(value) if value else value


class PersonUpdate(BaseModel):
    full_name: str | None = None
    alternate_phone: str | None = None
    email: str | None = None
    gender: str | None = None
    date_of_birth: datetime | None = None
    address: Address | None = None
    preferred_language: str | None = None
    notes: str | None = None

    @field_validator("alternate_phone")
    @classmethod
    def _normalize_alternate_phone(cls, value: str | None) -> str | None:
        return normalize_phone_number(value) if value else value


class PersonOut(BaseModel):
    id: str
    full_name: str | None = None
    phone_number: str
    alternate_phone: str | None = None
    email: str | None = None
    gender: str | None = None
    date_of_birth: datetime | None = None
    address: Address | None = None
    preferred_language: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
