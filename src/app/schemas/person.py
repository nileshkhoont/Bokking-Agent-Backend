from datetime import datetime

from pydantic import BaseModel

from app.models.person import Address


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


class PersonUpdate(BaseModel):
    full_name: str | None = None
    alternate_phone: str | None = None
    email: str | None = None
    gender: str | None = None
    date_of_birth: datetime | None = None
    address: Address | None = None
    preferred_language: str | None = None
    notes: str | None = None


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
