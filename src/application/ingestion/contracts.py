"""Input and output contracts for ingestion application flows."""

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
