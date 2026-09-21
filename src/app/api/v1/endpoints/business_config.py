from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_admin
from app.core.exceptions import NotFoundError
from app.models.admin import Admin
from app.models.business_config import BusinessConfig, Holiday, WorkingHours

router = APIRouter(prefix="/business-config", tags=["business_config"])


class BusinessConfigUpdate(BaseModel):
    working_days: list[str] | None = None
    working_hours: list[WorkingHours] | None = None
    slot_duration_minutes: int | None = None
    buffer_minutes: int | None = None
    holidays: list[Holiday] | None = None
    max_advance_booking_days: int | None = None
    timezone: str | None = None


@router.get("", response_model=BusinessConfig)
async def get_business_config(_: Admin = Depends(get_current_admin)) -> BusinessConfig:
    config = await BusinessConfig.find_one({})
    if config is None:
        raise NotFoundError("business_config is not set up — run scripts/seed_business_config.py")
    return config


@router.patch("", response_model=BusinessConfig)
async def update_business_config(
    payload: BusinessConfigUpdate, _: Admin = Depends(get_current_admin)
) -> BusinessConfig:
    config = await BusinessConfig.find_one({})
    if config is None:
        config = BusinessConfig()

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(config, field, value)
    config.updated_at = datetime.now(UTC)
    await config.save()
    return config
