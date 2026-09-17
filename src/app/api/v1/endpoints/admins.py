from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pymongo.errors import DuplicateKeyError

from app.api.deps import get_current_admin, get_page_params, require_role
from app.core.constants import ActorType, AdminRole, AuditAction
from app.core.exceptions import AppError, NotFoundError
from app.core.security import hash_password
from app.models.admin import Admin
from app.schemas.admin import AdminCreate, AdminOut, AdminUpdate
from app.schemas.common import Page, PageParams
from app.services.audit_service import audit_service
from app.utils.pagination import build_page

router = APIRouter(prefix="/admins", tags=["admins"])


def _to_out(admin: Admin) -> AdminOut:
    return AdminOut(
        id=str(admin.id),
        name=admin.name,
        email=admin.email,
        phone_number=admin.phone_number,
        role=admin.role,
        is_active=admin.is_active,
        last_login_at=admin.last_login_at,
        created_at=admin.created_at,
    )


@router.get("/me", response_model=AdminOut)
async def get_my_profile(current: Admin = Depends(get_current_admin)) -> AdminOut:
    return _to_out(current)


@router.get("", response_model=Page[AdminOut])
async def list_admins(
    page: PageParams = Depends(get_page_params),
    _: Admin = Depends(require_role(AdminRole.super_admin, AdminRole.admin)),
) -> Page[AdminOut]:
    query = Admin.find(Admin.is_deleted == False)  # noqa: E712
    total = await query.count()
    items = await query.sort(-Admin.created_at).skip(page.skip).limit(page.page_size).to_list()
    return build_page([_to_out(a) for a in items], total, page)


@router.post("", response_model=AdminOut, status_code=201)
async def create_admin(
    payload: AdminCreate, current: Admin = Depends(require_role(AdminRole.super_admin))
) -> AdminOut:
    admin = Admin(
        name=payload.name,
        email=payload.email.lower(),
        phone_number=payload.phone_number,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    try:
        await admin.insert()
    except DuplicateKeyError as exc:
        raise AppError("An admin with this email already exists") from exc

    await audit_service.record(
        actor_type=ActorType.admin,
        action=AuditAction.create,
        entity_type="admin",
        entity_id=str(admin.id),
        actor_id=str(current.id),
        after=_to_out(admin).model_dump(mode="json"),
    )
    return _to_out(admin)


@router.patch("/{admin_id}", response_model=AdminOut)
async def update_admin(
    admin_id: str,
    payload: AdminUpdate,
    current: Admin = Depends(require_role(AdminRole.super_admin)),
) -> AdminOut:
    admin = await Admin.get(admin_id)
    if admin is None or admin.is_deleted:
        raise NotFoundError("Admin not found")

    before = _to_out(admin).model_dump(mode="json")
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(admin, field, value)
    await admin.save()

    await audit_service.record(
        actor_type=ActorType.admin,
        action=AuditAction.update,
        entity_type="admin",
        entity_id=str(admin.id),
        actor_id=str(current.id),
        before=before,
        after=_to_out(admin).model_dump(mode="json"),
    )
    return _to_out(admin)


@router.delete("/{admin_id}", status_code=204)
async def delete_admin(
    admin_id: str, current: Admin = Depends(require_role(AdminRole.super_admin))
) -> None:
    admin = await Admin.get(admin_id)
    if admin is None or admin.is_deleted:
        raise NotFoundError("Admin not found")

    admin.is_deleted = True
    admin.deleted_at = datetime.now(UTC)
    await admin.save()

    await audit_service.record(
        actor_type=ActorType.admin,
        action=AuditAction.delete,
        entity_type="admin",
        entity_id=str(admin.id),
        actor_id=str(current.id),
    )
