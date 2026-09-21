from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

WEEKDAY_NAMES = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

# The business's confirmed operating timezone — India Standard Time, fixed UTC+5:30, no DST.
# Used as the assumed zone for any datetime that arrives with no explicit offset (from the admin
# UI or the AI agent), since both operate in IST. MongoDB reads never produce naive datetimes
# (the Motor client is configured tz_aware=True in db/mongodb.py), so this only ever applies to
# genuinely ambiguous external input, never to a value already read back from the database.
BUSINESS_TIMEZONE = ZoneInfo("Asia/Kolkata")


def ensure_utc(value: datetime) -> datetime:
    """Store/compare all datetimes in UTC (schema doc §10). A naive datetime (no tzinfo) is
    assumed to be India Standard Time, not UTC — see BUSINESS_TIMEZONE above.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=BUSINESS_TIMEZONE)
    return value.astimezone(UTC)


def to_business_timezone(value: datetime, tz_name: str | None) -> datetime:
    value = ensure_utc(value)
    if not tz_name:
        return value
    return value.astimezone(ZoneInfo(tz_name))


def parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(hour=int(hour), minute=int(minute))


def is_same_calendar_day(a: datetime, b: datetime) -> bool:
    return a.date() == b.date()


def add_minutes(value: datetime, minutes: int) -> datetime:
    return value + timedelta(minutes=minutes)


def format_ist_human(value: datetime) -> str:
    """Human-readable IST rendering for anything handed back to the AI agent (agent_tools
    responses) — an LLM reading a raw UTC ISO timestamp has to do timezone math itself to speak
    the correct local time; handing it this string instead means it just reads it aloud.
    """
    ist = ensure_utc(value).astimezone(BUSINESS_TIMEZONE)
    return ist.strftime("%A, %d %B %Y, %I:%M %p IST").replace(" 0", " ")


def format_ist_time(value: datetime) -> str:
    """Time-only IST rendering (e.g. "10:00 AM") — for reading out a list of same-day slot
    options, where repeating the full date for every option would be tedious to listen to.
    """
    ist = ensure_utc(value).astimezone(BUSINESS_TIMEZONE)
    return ist.strftime("%I:%M %p").lstrip("0")
