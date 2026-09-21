from datetime import datetime

import pymongo
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
        indexes = [
            pymongo.IndexModel([("full_name", pymongo.TEXT)]),
        ]
