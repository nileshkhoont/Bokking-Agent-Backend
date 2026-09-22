from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models.business_config import BusinessConfig, WorkingHours
from app.repositories.appointment_repository import appointment_repository
from app.schemas.appointment import SlotCheckResponse
from app.utils.datetime_utils import (
    BUSINESS_TIMEZONE,
    WEEKDAY_NAMES,
    ensure_utc,
    parse_hhmm,
    to_business_timezone,
)


def _minutes_since_midnight(value: time) -> int:
    return value.hour * 60 + value.minute


def _in_window(local_time: time, window: WorkingHours) -> bool:
    start, end = parse_hhmm(window.start), parse_hhmm(window.end)
    return start <= local_time < end


def _fits_and_aligns(local_time: time, window: WorkingHours, slot_duration_minutes: int) -> bool:
    """True if a slot_duration_minutes-long slot starting at local_time both lands on this
    window's slot grid AND finishes before the window closes — e.g. for an 11:00-13:30 window
    with 20-min slots, 13:00 is valid (ends 13:20, still inside) but 13:20 is not (would end
    13:40, past closing), even though 13:20 itself falls inside the window and on the grid.
    """
    start_m = _minutes_since_midnight(parse_hhmm(window.start))
    end_m = _minutes_since_midnight(parse_hhmm(window.end))
    t_m = _minutes_since_midnight(local_time)
    if t_m < start_m or t_m + slot_duration_minutes > end_m:
        return False
    return (t_m - start_m) % slot_duration_minutes == 0


def _format_windows(windows: list[WorkingHours]) -> str:
    return ", ".join(f"{w.start}-{w.end}" for w in windows)


@dataclass(slots=True)
class DayAvailability:
    """A day's open slots *plus why there are none*, when there are none.

    An empty slot list on its own is ambiguous — a day the business is simply closed and a
    working day whose slots are all taken look identical. On 2026-09-22 a caller asked about
    25 and 27 September (both non-working days) and the agent could only say "koi slots khali
    nathi", which sounds like the clinic is booked out rather than shut. Carrying the reason
    alongside the slots lets the caller be told the useful thing — which days the clinic is
    actually open — without the agent having to remember working_days from its prompt and drift
    out of sync with business_config.
    """

    slots: list[datetime]
    is_working_day: bool
    closed_reason: str | None
    working_days: list[str]


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

        windows = [w for w in config.working_hours if w.start and w.end]
        if windows:
            local_time = local_dt.time()
            if not any(_in_window(local_time, w) for w in windows):
                return SlotCheckResponse(
                    available=False,
                    reason=f"Requested time is outside working hours ({_format_windows(windows)})",
                )

            if require_slot_alignment and config.slot_duration_minutes:
                if not any(
                    _fits_and_aligns(local_time, w, config.slot_duration_minutes) for w in windows
                ):
                    return SlotCheckResponse(
                        available=False,
                        reason=(
                            f"Requested time does not align to {config.slot_duration_minutes}-minute "
                            "slots, or would run past closing time"
                        ),
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

    async def list_available_slots(self, on_date: date) -> list[datetime]:
        """Every bookable slot start time (UTC) on a given calendar date. Thin wrapper over
        describe_day for callers that only need the times themselves.
        """
        return (await self.describe_day(on_date)).slots

    async def get_working_days(self) -> list[str]:
        config = await self._get_config()
        return [day.capitalize() for day in config.working_days]

    async def describe_day(self, on_date: date) -> DayAvailability:
        """Every bookable slot start time (UTC) on a given calendar date — generated live from
        business_config's working windows/slot_duration and filtered against real bookings and
        the same past/holiday/advance-window rules check_availability enforces for one candidate.
        Computed fresh on every call rather than stored, so it can never go stale relative to
        business_config or a booking made a second ago (folder-structure doc: booking rules stay
        in one place regardless of caller).
        """
        config = await self._get_config()
        working_days = [day.capitalize() for day in config.working_days]

        def closed(reason: str) -> DayAvailability:
            return DayAvailability(
                slots=[], is_working_day=False, closed_reason=reason, working_days=working_days
            )

        if not config.slot_duration_minutes:
            return DayAvailability(
                slots=[], is_working_day=True, closed_reason=None, working_days=working_days
            )

        tz = ZoneInfo(config.timezone) if config.timezone else BUSINESS_TIMEZONE
        local_midnight = datetime.combine(on_date, time.min, tzinfo=tz)

        weekday_name = WEEKDAY_NAMES[local_midnight.weekday()]
        if config.working_days and weekday_name not in [d.lower() for d in config.working_days]:
            return closed(f"Business is closed on {weekday_name.capitalize()}s")

        for holiday in config.holidays:
            holiday_local = to_business_timezone(ensure_utc(holiday.date), config.timezone)
            if holiday_local.date() == on_date:
                return closed(f"Business is closed for a holiday ({holiday.reason or 'holiday'})")

        now_utc = datetime.now(UTC)
        max_advance_utc = None
        if config.max_advance_booking_days is not None:
            max_advance_utc = now_utc.replace(
                hour=23, minute=59, second=59, microsecond=0
            ) + timedelta(days=config.max_advance_booking_days)

        candidates: list[datetime] = []
        for window in config.working_hours:
            if not (window.start and window.end):
                continue
            start_m = _minutes_since_midnight(parse_hhmm(window.start))
            end_m = _minutes_since_midnight(parse_hhmm(window.end))
            for t_m in range(start_m, end_m, config.slot_duration_minutes):
                if t_m + config.slot_duration_minutes > end_m:
                    break
                candidate_utc = (local_midnight + timedelta(minutes=t_m)).astimezone(UTC)
                if candidate_utc <= now_utc:
                    continue
                if max_advance_utc is not None and candidate_utc > max_advance_utc:
                    continue
                candidates.append(candidate_utc)

        open_slots: list[datetime] = []
        if candidates:
            day_start_utc = local_midnight.astimezone(UTC)
            day_end_utc = (local_midnight + timedelta(days=1)).astimezone(UTC)
            booked = await appointment_repository.list_active_between(day_start_utc, day_end_utc)
            booked_at = {a.appointment_datetime for a in booked}
            open_slots = [c for c in candidates if c not in booked_at]

        # A working day with nothing left is genuinely "fully booked" (or already past for
        # today) — not closed. The caller needs to hear those two things differently.
        return DayAvailability(
            slots=open_slots, is_working_day=True, closed_reason=None, working_days=working_days
        )

    async def check_callback_time_valid(self, requested_datetime: datetime) -> SlotCheckResponse:
        """Validates a person-requested callback datetime — working days/hours/holidays/max
        advance window only, no appointment-slot alignment or double-booking check (a callback
        isn't an appointment).
        """
        config = await self._get_config()
        requested_utc = ensure_utc(requested_datetime)
        return await self._check_business_hours(config, requested_utc, require_slot_alignment=False)


slot_service = SlotService()
