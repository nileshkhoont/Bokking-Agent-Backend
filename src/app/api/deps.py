from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.constants import AdminRole
from app.core.security import decode_token
from app.models.admin import Admin
from app.schemas.common import PageParams

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Admin:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        admin_id = decode_token(credentials.credentials, expected_type="access")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    admin = await Admin.get(admin_id)
    if admin is None or admin.is_deleted or not admin.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin not found or inactive")
    return admin


def require_role(*roles: AdminRole):
    async def _check(admin: Admin = Depends(get_current_admin)) -> Admin:
        if admin.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return admin

    return _check


async def get_page_params(page: int = 1, page_size: int = 20) -> PageParams:
    return PageParams(page=page, page_size=page_size)
