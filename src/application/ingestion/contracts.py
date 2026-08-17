"""Input, output contracts, and error classification for ingestion application flows."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from src.core.types import ProcessingStats
from src.domain.ingestion.models import ReconciliationFile


@dataclass(frozen=True, slots=True)
class ProcessFileCommand:
    """All inputs required to process one source file."""

    file_path: str
    partner: str
    workflow_type: str
    file_type: Any
    reconciliation_date: Any
    config_version: str | None = None
    backfill_run_id: str | None = None
    fetch_unit_metadata: dict[str, Any] | None = None
    enable_config_health_check: bool = False


@dataclass
class IngestionResult:
    """Outcome returned by the ingestion application boundary."""

    file_record: ReconciliationFile | None
    stats: ProcessingStats
    errors: list[dict[str, Any]] = field(default_factory=list)
    outcome: Literal[
        "INGESTED",
        "FILE_DUPLICATE",
        "FETCH_UNIT_REPLAY",
        "WAITING_REVIEW",
        "FAILED",
    ] = "INGESTED"
    duplicate_code: str | None = None
    ingestion_keys: list[str] = field(default_factory=list)
    quality_counters: dict[str, int] = field(default_factory=dict)


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


__all__ = [
    "ProcessFileCommand",
    "IngestionResult",
    "is_missing_ingestion_key_failure",
]
