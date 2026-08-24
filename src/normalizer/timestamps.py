"""Pure timestamp parsing for canonical partner transactions."""

from datetime import UTC, datetime
from typing import Final


LEGACY_TIMESTAMP_FORMATS: Final[tuple[str, ...]] = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
)


class TimestampParseError(ValueError):
    """Raised when a source value cannot become canonical transDate."""


def _normalize_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value
    return value.astimezone(UTC)


def parse_transaction_timestamp(value: object) -> datetime:
    """Parse one timestamp without applying partner timezone policy."""
    if isinstance(value, datetime):
        return _normalize_aware(value)
    if not isinstance(value, str) or not value:
        raise TimestampParseError("unsupported timestamp")

    iso_candidate = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(iso_candidate)
    except ValueError:
        parsed = None
    if (
        parsed is not None
        and parsed.tzinfo is not None
        and parsed.utcoffset() is not None
    ):
        return parsed.astimezone(UTC)

    for date_format in LEGACY_TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(value, date_format)
        except ValueError:
            continue

    raise TimestampParseError("unsupported timestamp")


__all__ = ["TimestampParseError", "parse_transaction_timestamp"]
