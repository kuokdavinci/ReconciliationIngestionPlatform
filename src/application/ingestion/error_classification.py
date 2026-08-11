"""Shared classification helpers for ingestion failures."""

from collections.abc import Iterable, Mapping
from typing import Any


def is_missing_ingestion_key_failure(
    *,
    total_rows: int,
    success_rows: int,
    failed_rows: int,
    errors: Iterable[Any],
) -> bool:
    """Return whether every source row failed because both identity fields are absent."""
    error_fields = {
        str(error.get("field"))
        for error in errors
        if isinstance(error, Mapping) and error.get("field")
    }
    return (
        total_rows > 0
        and success_rows == 0
        and failed_rows >= total_rows
        and {"id", "trace"}.issubset(error_fields)
    )
