from datetime import UTC, datetime, timedelta

from app.models.business_config import BusinessConfig
from app.repositories.appointment_repository import appointment_repository
from app.schemas.appointment import SlotCheckResponse
from app.utils.datetime_utils import (
    WEEKDAY_NAMES,
    align_to_slot_boundary,
    ensure_utc,
    parse_hhmm,
    to_business_timezone,
)


class SlotService:
    async def _get_config(self) -> BusinessConfig:
        config = await BusinessConfig.find_one({})
        if config is None:
            raise ValueError(
                "business_config is not set up — run scripts/seed_business_config.py first"
            )
        return config

    async def _check_business_hours(
        self, config: BusinessConfig, requested_utc: datetime, require_slot_alignment: bool
    ) -> SlotCheckResponse:
        """Working days/hours/holidays/max-advance-window checks shared by appointment slot
        checks and person-requested-callback validation (schema doc §10 — a callback time must be
        "caught the same way an unavailable appointment slot is").
        """
        now_utc = datetime.now(UTC)

        if requested_utc <= now_utc:
            return SlotCheckResponse(available=False, reason="Requested time is in the past")

        if config.max_advance_booking_days is not None:
            max_advance = now_utc.replace(hour=23, minute=59, second=59, microsecond=0)
            max_advance = max_advance + timedelta(days=config.max_advance_booking_days)
            if requested_utc > max_advance:
                return SlotCheckResponse(
                    available=False,
                    reason=(
                        f"Requested time is beyond the {config.max_advance_booking_days}-day "
                        "advance booking window"
                    ),
                )

        local_dt = to_business_timezone(requested_utc, config.timezone)

        weekday_name = WEEKDAY_NAMES[local_dt.weekday()]
        if config.working_days and weekday_name not in [d.lower() for d in config.working_days]:
            return SlotCheckResponse(
                available=False, reason=f"Business is closed on {weekday_name.capitalize()}"
            )

        for holiday in config.holidays:
            holiday_local = to_business_timezone(ensure_utc(holiday.date), config.timezone)
            if holiday_local.date() == local_dt.date():
                reason = f"Business is closed for a holiday ({holiday.reason or 'holiday'})"
                return SlotCheckResponse(available=False, reason=reason)

        if config.working_hours and config.working_hours.start and config.working_hours.end:
            start_time = parse_hhmm(config.working_hours.start)
            end_time = parse_hhmm(config.working_hours.end)
            if not (start_time <= local_dt.time() < end_time):
                return SlotCheckResponse(
                    available=False,
                    reason=(
                        f"Requested time is outside working hours "
                        f"({config.working_hours.start}-{config.working_hours.end})"
                    ),
                )

            if (
                require_slot_alignment
                and config.slot_duration_minutes
                and not align_to_slot_boundary(local_dt, start_time, config.slot_duration_minutes)
            ):
                return SlotCheckResponse(
                    available=False,
                    reason=f"Requested time does not align to {config.slot_duration_minutes}-minute slots",
                )

        return SlotCheckResponse(available=True)

    async def check_availability(
        self,
        requested_datetime: datetime,
        exclude_appointment_id: str | None = None,
    ) -> SlotCheckResponse:
        """The one slot-availability check both the admin API and the agent's
        check_slot_availability tool call into (folder-structure doc: "booking rules stay in one
        place regardless of whether the booking came from a human admin or the AI agent mid-call").
        """
        config = await self._get_config()
        requested_utc = ensure_utc(requested_datetime)

        business_hours_check = await self._check_business_hours(
            config, requested_utc, require_slot_alignment=True
        )
        if not business_hours_check.available:
            return business_hours_check

        already_booked = await appointment_repository.exists_active_at(
            requested_utc, exclude_appointment_id=exclude_appointment_id
        )
        if already_booked:
            return SlotCheckResponse(available=False, reason="Slot is already booked")

        return SlotCheckResponse(available=True)

    async def check_callback_time_valid(self, requested_datetime: datetime) -> SlotCheckResponse:
        """Validates a person-requested callback datetime — working days/hours/holidays/max
        advance window only, no appointment-slot alignment or double-booking check (a callback
        isn't an appointment).
        """
        config = await self._get_config()
        requested_utc = ensure_utc(requested_datetime)
        return await self._check_business_hours(config, requested_utc, require_slot_alignment=False)


slot_service = SlotService()
