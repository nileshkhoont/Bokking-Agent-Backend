from datetime import UTC, datetime

from fastapi import APIRouter

from app.core.exceptions import InvalidCredentialsError
from app.core.security import create_access_token, create_refresh_token, decode_token, verify_password
from app.models.admin import Admin
from app.schemas.admin import LoginRequest, RefreshRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest) -> TokenResponse:
    admin = await Admin.find_one(Admin.email == payload.email.lower())
    if admin is None or admin.is_deleted or not admin.is_active:
        raise InvalidCredentialsError()

    if not verify_password(payload.password, admin.password_hash):
        raise InvalidCredentialsError()

    admin.last_login_at = datetime.now(UTC)
    await admin.save()

    admin_id = str(admin.id)
    return TokenResponse(
        access_token=create_access_token(admin_id), refresh_token=create_refresh_token(admin_id)
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest) -> TokenResponse:
    try:
        admin_id = decode_token(payload.refresh_token, expected_type="refresh")
    except ValueError as exc:
        raise InvalidCredentialsError(str(exc)) from exc

    admin = await Admin.get(admin_id)
    if admin is None or admin.is_deleted or not admin.is_active:
        raise InvalidCredentialsError("Admin not found or inactive")

    return TokenResponse(
        access_token=create_access_token(admin_id), refresh_token=create_refresh_token(admin_id)
    )
