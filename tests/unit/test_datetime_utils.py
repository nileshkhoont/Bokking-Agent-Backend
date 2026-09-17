from datetime import UTC, datetime

from app.utils.datetime_utils import ensure_utc, format_ist_human


def test_naive_datetime_is_assumed_to_be_ist():
    # 10:00 with no offset must be treated as 10:00 IST, i.e. 04:30 UTC (IST is UTC+5:30).
    naive = datetime(2026, 9, 20, 10, 0, 0)
    result = ensure_utc(naive)

    assert result.tzinfo == UTC
    assert result.hour == 4
    assert result.minute == 30


def test_aware_datetime_offset_is_respected_not_reinterpreted():
    # An explicit UTC timestamp must stay exactly as given, not be shifted as if it were IST.
    aware_utc = datetime(2026, 9, 20, 4, 30, 0, tzinfo=UTC)
    result = ensure_utc(aware_utc)

    assert result == aware_utc


def test_format_ist_human_renders_ist_wall_clock_time():
    utc_value = datetime(2026, 9, 20, 4, 30, 0, tzinfo=UTC)
    rendered = format_ist_human(utc_value)

    assert "10:00 AM" in rendered
    assert "IST" in rendered
    assert "2026" in rendered
