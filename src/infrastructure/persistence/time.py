"""Shared timestamp normalization for PostgreSQL persistence boundaries."""

from datetime import datetime, timezone
from typing import overload


@overload
def as_utc_naive(value: datetime) -> datetime: ...


@overload
def as_utc_naive(value: None) -> None: ...


@overload
def as_utc_naive(value: datetime | None) -> datetime | None: ...


def as_utc_naive(value: datetime | None) -> datetime | None:
    """Return a timestamp in PostgreSQL's UTC-naive convention.

    Naive values are already treated as UTC-naive because MongoDB and the
    PostgreSQL schema both persist them without timezone information.
    """

    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)
