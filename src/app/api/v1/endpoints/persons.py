from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pymongo.errors import DuplicateKeyError

from app.api.deps import get_current_admin, get_page_params
from app.core.constants import ActorType, AuditAction
from app.core.exceptions import AppError, NotFoundError
from app.models.admin import Admin
from app.models.person import Person
from app.repositories.person_repository import person_repository
from app.schemas.common import Page, PageParams
from app.schemas.person import PersonCreate, PersonOut, PersonUpdate
from app.services.audit_service import audit_service
from app.utils.pagination import build_page

router = APIRouter(prefix="/persons", tags=["persons"])


def _to_out(person: Person) -> PersonOut:
    return PersonOut(
        id=str(person.id),
        full_name=person.full_name,
        phone_number=person.phone_number,
        alternate_phone=person.alternate_phone,
        email=person.email,
        gender=person.gender,
        date_of_birth=person.date_of_birth,
        address=person.address,
        preferred_language=person.preferred_language,
        notes=person.notes,
        created_at=person.created_at,
        updated_at=person.updated_at,
    )


@router.get("", response_model=Page[PersonOut])
async def list_persons(
    q: str | None = Query(default=None, description="Search by name or phone number"),
    page: PageParams = Depends(get_page_params),
    _: Admin = Depends(get_current_admin),
) -> Page[PersonOut]:
    items, total = await person_repository.search(q, page)
    return build_page([_to_out(p) for p in items], total, page)


@router.get("/{person_id}", response_model=PersonOut)
async def get_person(person_id: str, _: Admin = Depends(get_current_admin)) -> PersonOut:
    person = await person_repository.get_by_id(person_id)
    if person is None:
        raise NotFoundError("Person not found")
    return _to_out(person)


@router.post("", response_model=PersonOut, status_code=201)
async def create_person(
    payload: PersonCreate, current: Admin = Depends(get_current_admin)
) -> PersonOut:
    person = Person(**payload.model_dump())
    try:
        await person.insert()
    except DuplicateKeyError as exc:
        raise AppError("A person with this phone number already exists") from exc

    await audit_service.record(
        actor_type=ActorType.admin,
        action=AuditAction.create,
        entity_type="person",
        entity_id=str(person.id),
        actor_id=str(current.id),
        after=_to_out(person).model_dump(mode="json"),
    )
    return _to_out(person)


@router.patch("/{person_id}", response_model=PersonOut)
async def update_person(
    person_id: str, payload: PersonUpdate, current: Admin = Depends(get_current_admin)
) -> PersonOut:
    person = await person_repository.get_by_id(person_id)
    if person is None:
        raise NotFoundError("Person not found")

    before = _to_out(person).model_dump(mode="json")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(person, field, value)
    await person.save()

    await audit_service.record(
        actor_type=ActorType.admin,
        action=AuditAction.update,
        entity_type="person",
        entity_id=str(person.id),
        actor_id=str(current.id),
        before=before,
        after=_to_out(person).model_dump(mode="json"),
    )
    return _to_out(person)


@router.delete("/{person_id}", status_code=204)
async def delete_person(person_id: str, current: Admin = Depends(get_current_admin)) -> None:
    person = await person_repository.get_by_id(person_id)
    if person is None:
        raise NotFoundError("Person not found")

    person.is_deleted = True
    person.deleted_at = datetime.now(UTC)
    await person.save()

    await audit_service.record(
        actor_type=ActorType.admin,
        action=AuditAction.delete,
        entity_type="person",
        entity_id=str(person.id),
        actor_id=str(current.id),
    )
