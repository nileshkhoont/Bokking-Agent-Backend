from datetime import datetime

from beanie import Indexed
from pydantic import BaseModel

from app.db.base import TimestampedDocument


class Address(BaseModel):
    line1: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None
    country: str | None = None


class Person(TimestampedDocument):
    full_name: str | None = None
    phone_number: Indexed(str, unique=True)  # E.164, e.g. "+919876543210" — natural identity key
    alternate_phone: str | None = None
    email: str | None = None
    gender: str | None = None  # "male" | "female" | "other" | None
    date_of_birth: datetime | None = None
    address: Address | None = None
    preferred_language: str | None = None
    notes: str | None = None

    class Settings(TimestampedDocument.Settings):
        name = "persons"
        # No longer indexed on full_name: search (person_repository.py's _name_or_phone_filter)
        # switched from a $text query (which needed this TEXT index, and only matched whole
        # words) to a plain $regex substring match, which doesn't use an index either way. Any
        # existing deployed database still physically has this index — Beanie's init_beanie here
        # isn't given allow_index_dropping=True, so it was never auto-dropped — it's just unused
        # dead weight now; drop it manually (db.persons.dropIndex("full_name_text")) if desired.
