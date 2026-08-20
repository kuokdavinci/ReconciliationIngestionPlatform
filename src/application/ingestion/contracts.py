"""Input, output contracts, and error classification for ingestion application flows."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from src.core.types import ProcessingStats
from src.domain.ingestion.models import ReconciliationFile
from src.domain.ingestion.quality import (
    QualityDecision,
    QualitySummary,
    QualityViolation,
)
from src.application.ingestion.quality_policy import OrchestrationAction


def serialize_quality_violation(violation: QualityViolation) -> dict[str, Any]:
    """Serialize a domain violation at the existing application error boundary."""

    canonical = violation.model_dump(mode="json", exclude_none=True)
    payload: dict[str, Any] = {
        "field": canonical.pop("field", None),
        "reason": canonical.pop("message"),
        "errorCode": canonical.pop("code"),
    }
    aliases = {"config_version": "configVersion"}
    for key, value in canonical.items():
        payload[aliases.get(key, key)] = value
    return payload


def serialize_quality_summary(
    summary: QualitySummary,
    action: OrchestrationAction,
) -> dict[str, Any]:
    """Serialize the bounded stage/application quality summary."""

    return {
        "decision": summary.decision.value,
        "action": action.value,
        "ruleCounts": dict(summary.rule_counts),
        "outcomeCounts": dict(summary.outcome_counts),
        "topRuleCodes": list(summary.top_rule_codes[:10]),
    }


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
    quality_decision: QualityDecision = QualityDecision.PASS
    quality_summary: QualitySummary = field(default_factory=QualitySummary)
    orchestration_action: OrchestrationAction = OrchestrationAction.CONTINUE

    def bounded_source_unit_result(self) -> dict[str, Any]:
        """Return the bounded, machine-readable Airflow-facing result."""

        return {
            "success": self.outcome != "FAILED",
            "outcome": self.outcome,
            "qualityDecision": self.quality_decision.value,
            "orchestrationAction": self.orchestration_action.value,
            "qualityCounters": dict(self.quality_counters),
            "topRuleCodes": list(self.quality_summary.top_rule_codes[:10]),
        }


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
    "serialize_quality_summary",
    "serialize_quality_violation",
]
