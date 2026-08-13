"""Business-calendar date and timezone boundary helpers."""

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from src.config.settings import settings


def business_date(value: datetime) -> date:
    """Resolve a timestamp to the configured local business date."""

    utc_value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return utc_value.astimezone(ZoneInfo(settings.business_timezone)).date()


def business_day_bounds(value: datetime) -> tuple[datetime, datetime]:
    """Return local timezone-aware bounds for one business date."""

    business_timezone = ZoneInfo(settings.business_timezone)
    resolved_date = business_date(value)
    return (
        datetime.combine(resolved_date, time.min, tzinfo=business_timezone),
        datetime.combine(resolved_date, time.max, tzinfo=business_timezone),
    )


def utc_business_day_bounds(value: datetime) -> tuple[datetime, datetime]:
    """Return UTC-aware bounds for one business date."""

    start, end = business_day_bounds(value)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
