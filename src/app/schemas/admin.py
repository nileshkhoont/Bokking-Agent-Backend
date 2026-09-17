from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.core.constants import AdminRole


class AdminCreate(BaseModel):
    name: str
    email: EmailStr
    phone_number: str | None = None
    password: str = Field(min_length=8)
    role: AdminRole = AdminRole.admin


class AdminUpdate(BaseModel):
    name: str | None = None
    phone_number: str | None = None
    role: AdminRole | None = None
    is_active: bool | None = None


class AdminOut(BaseModel):
    id: str
    name: str
    email: str
    phone_number: str | None = None
    role: AdminRole
    is_active: bool
    last_login_at: datetime | None = None
    created_at: datetime


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str
