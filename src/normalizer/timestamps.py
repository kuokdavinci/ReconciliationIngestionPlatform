"""Pure timestamp parsing for canonical partner transactions."""

from datetime import UTC, datetime
import re
from typing import Final


LEGACY_TIMESTAMP_FORMATS: Final[tuple[str, ...]] = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
)

_OFFSET_TIMESTAMP_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})"
)


class TimestampParseError(ValueError):
    """Raised when a source value cannot become canonical transDate."""


def _normalize_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value
    try:
        return value.astimezone(UTC)
    except OverflowError as error:
        raise TimestampParseError("unsupported timestamp") from error


def parse_transaction_timestamp(value: object) -> datetime:
    """Parse one timestamp without applying partner timezone policy."""
    if isinstance(value, datetime):
        return _normalize_aware(value)
    if not isinstance(value, str) or not value:
        raise TimestampParseError("unsupported timestamp")

    if _OFFSET_TIMESTAMP_PATTERN.fullmatch(value):
        iso_candidate = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        try:
            return _normalize_aware(datetime.fromisoformat(iso_candidate))
        except ValueError:
            pass

    for date_format in LEGACY_TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(value, date_format)
        except ValueError:
            continue

    raise TimestampParseError("unsupported timestamp")


__all__ = ["TimestampParseError", "parse_transaction_timestamp"]
