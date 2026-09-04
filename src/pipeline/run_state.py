"""Mutable state for one ingestion run."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
import time
from typing import Any

from src.application.ingestion.contracts import (
    serialize_quality_summary,
    serialize_quality_violation,
)
from src.application.ingestion.quality_policy import (
    OrchestrationAction,
)
from src.domain.ingestion.quality import (
    QualityDecision,
    QualityEvaluation,
    QualityOutcome,
    QualityPhase,
    QualityRuleCode,
    QualitySeverity,
    QualitySummary,
    QualityViolation,
)
from src.core.types import ProcessingStats
from src.domain.partner_transaction.duplicates import BatchWriteResult
from src.core.utils import sanitize_runtime_error


ERROR_SAMPLE_LIMIT = 5


@dataclass
class IngestionRunState:
    """Track row outcomes without coupling accounting to pipeline orchestration."""

    total_rows: int = 0
    success_rows: int = 0
    failed_rows: int = 0
    duplicate_rows: int = 0
    rejected_rows: int = 0
    persistence_failed_rows: int = 0
    quarantined_rows: int = 0
    equivalent_duplicate_rows: int = 0
    conflicting_duplicate_rows: int = 0
    warning_rows: int = 0
    quality_rule_counts: dict[str, int] = field(default_factory=dict)
    quality_outcome_counts: dict[str, int] = field(default_factory=dict)
    quality_decision: QualityDecision = QualityDecision.PASS
    orchestration_action: OrchestrationAction = OrchestrationAction.CONTINUE
    errors: list[dict[str, Any]] = field(default_factory=list)
    ingestion_keys: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    current_stage: str | None = None
    last_error: str | None = None
    last_error_code: str | None = None
    run_id: str | None = None
    partner: str | None = None
    attempt: int = 1
    source_file_id: str | None = None
    current_unit_key: str | None = None
    current_page: int | None = None
    checkpoint_before: dict[str, Any] = field(default_factory=dict)
    checkpoint_after: dict[str, Any] = field(default_factory=dict)
    stage_durations_ms: dict[str, float] = field(default_factory=dict)
    batch_metrics: dict[str, float | int] = field(default_factory=dict)
    error_count: int = 0
    error_samples_dropped: int = 0
    row_error_logs: int = 0
    _error_fields: set[str] = field(default_factory=set, repr=False)
    duration_ms: float | None = None
    _stage_started_at: float | None = field(default=None, repr=False)
    _run_started_at: float = field(default_factory=time.perf_counter, repr=False)

    def __post_init__(self) -> None:
        """Keep legacy constructor-provided samples useful for classification."""
        self.error_count = max(self.error_count, len(self.errors))
        self.error_fields.update(
            str(error["field"])
            for error in self.errors
            if isinstance(error, dict) and error.get("field")
        )

    def record_row(self) -> int:
        self.total_rows += 1
        return self.total_rows

    def record_invalid_row(
        self,
        errors: list[dict[str, Any]] | list[QualityViolation],
    ) -> None:
        self.failed_rows += 1
        self.rejected_rows += 1
        for item in errors:
            self.add_error(
                serialize_quality_violation(item)
                if isinstance(item, QualityViolation)
                else item
            )

    def record_valid_row(self, ingestion_key: str | None) -> None:
        self.ingestion_keys.append(ingestion_key or "")

    def record_row_outcome(self, outcome: Any) -> None:
        """Record one row outcome and update bounded quality aggregates."""

        if outcome.is_valid:
            self.record_valid_row(outcome.ingestion_key)
            if outcome.outcome is QualityOutcome.WARNING:
                for violation in outcome.violations:
                    self.add_error(serialize_quality_violation(violation))
        else:
            self.record_invalid_row(outcome.violations)
        self._record_quality(
            outcome.outcome,
            outcome.violations,
            count_warning_row=True,
        )

    def record_quality_evaluation(self, evaluation: QualityEvaluation) -> None:
        self._record_quality(
            evaluation.outcome,
            evaluation.violations,
            count_warning_row=evaluation.row_context.get("rowNumber") is not None,
        )

    def _record_quality(
        self,
        outcome: QualityOutcome,
        violations: list[QualityViolation],
        *,
        count_warning_row: bool,
    ) -> None:
        outcome_code = outcome.value
        self.quality_outcome_counts[outcome_code] = (
            self.quality_outcome_counts.get(outcome_code, 0) + 1
        )
        if outcome is QualityOutcome.VALID:
            return
        for violation in violations:
            code = violation.code.value
            self.quality_rule_counts[code] = self.quality_rule_counts.get(code, 0) + 1

        if outcome is QualityOutcome.CONFLICTING_DUPLICATE:
            self.conflicting_duplicate_rows += 1
        elif outcome is QualityOutcome.EQUIVALENT_DUPLICATE:
            self.equivalent_duplicate_rows += 1
        elif outcome is QualityOutcome.WARNING and count_warning_row:
            self.warning_rows += 1
        self._advance_quality_disposition(outcome)

    def add_error(self, error: dict[str, Any]) -> None:
        self.error_count += 1
        if error.get("field"):
            self.error_fields.add(str(error["field"]))
        if len(self.errors) < ERROR_SAMPLE_LIMIT:
            self.errors.append(error)
        else:
            self.error_samples_dropped += 1

    def should_log_row_error(self) -> bool:
        """Allow only a bounded sample of row-failure log events."""
        if self.row_error_logs >= ERROR_SAMPLE_LIMIT:
            return False
        self.row_error_logs += 1
        return True

    @property
    def error_fields(self) -> set[str]:
        return self._error_fields

    def begin_stage(self, stage: str) -> None:
        self.finish_stage()
        self.current_stage = stage
        self._stage_started_at = time.perf_counter()

    def set_source_context(
        self,
        *,
        run_id: str | None = None,
        partner: str | None = None,
        source_file_id: str | None = None,
        source_unit_key: str | None = None,
        page: int | None = None,
        checkpoint_before: dict[str, Any] | None = None,
        checkpoint_after: dict[str, Any] | None = None,
        attempt: int | None = None,
    ) -> None:
        """Attach bounded source context without retaining source rows."""
        if run_id is not None:
            self.run_id = str(run_id)
        if partner is not None:
            self.partner = str(partner)
        if source_file_id is not None:
            self.source_file_id = str(source_file_id)
        if source_unit_key is not None:
            self.current_unit_key = str(source_unit_key)
        if page is not None:
            self.current_page = page
        if checkpoint_before is not None:
            self.checkpoint_before = dict(checkpoint_before)
        if checkpoint_after is not None:
            self.checkpoint_after = dict(checkpoint_after)
        if attempt is not None:
            self.attempt = max(1, int(attempt))

    def finish_stage(self) -> None:
        if self.current_stage is None or self._stage_started_at is None:
            return
        duration = (time.perf_counter() - self._stage_started_at) * 1000
        self.stage_durations_ms[self.current_stage] = (
            self.stage_durations_ms.get(self.current_stage, 0.0) + duration
        )
        self._stage_started_at = None

    def finish_run(self) -> None:
        self.finish_stage()
        self.finished_at = datetime.now(UTC)
        self.duration_ms = max(0.0, (time.perf_counter() - self._run_started_at) * 1000)

    def record_error(self, error: Exception | str, error_code: str | None = None) -> None:
        self.last_error = sanitize_runtime_error(error)
        if error_code:
            self.last_error_code = sanitize_runtime_error(error_code, max_length=96)

    def merge_stage_summary(self, summary: dict[str, Any] | None) -> None:
        """Fold one source-file summary into a runtime summary."""
        if not isinstance(summary, dict):
            return
        durations = summary.get("stageDurationsMs") or {}
        if isinstance(durations, dict):
            for stage, value in durations.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    self.stage_durations_ms[str(stage)] = self.stage_durations_ms.get(
                        str(stage), 0.0
                    ) + max(0.0, float(value))
        batch_metrics = summary.get("batchMetrics") or {}
        if isinstance(batch_metrics, dict):
            self.record_batch_metrics(
                {
                    str(key): value
                    for key, value in batch_metrics.items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                }
            )
        counter_fields = {
            "inputRows": "total_rows",
            "persistedRows": "success_rows",
            "rejectedRows": "rejected_rows",
            "duplicateRows": "duplicate_rows",
            "persistenceFailedRows": "persistence_failed_rows",
            "quarantinedRows": "quarantined_rows",
        }
        for key, attribute in counter_fields.items():
            value = summary.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                setattr(self, attribute, getattr(self, attribute) + max(0, value))
        if summary.get("currentStage") is not None:
            self.current_stage = str(summary["currentStage"])
        if summary.get("currentUnitKey") is not None:
            self.current_unit_key = str(summary["currentUnitKey"])
        if summary.get("currentPage") is not None:
            self.current_page = summary["currentPage"]
        if isinstance(summary.get("checkpointBefore"), dict):
            self.checkpoint_before = dict(summary["checkpointBefore"])
        if isinstance(summary.get("checkpointAfter"), dict):
            self.checkpoint_after = dict(summary["checkpointAfter"])
        if summary.get("lastError"):
            self.last_error = sanitize_runtime_error(summary["lastError"])
        if summary.get("lastErrorCode"):
            self.last_error_code = sanitize_runtime_error(
                summary["lastErrorCode"], max_length=96
            )

    def record_batch_result(self, result: BatchWriteResult) -> None:
        self.success_rows += result.inserted
        self.duplicate_rows += result.duplicates
        self.failed_rows += result.failed
        self.persistence_failed_rows += result.failed
        for detail in result.duplicate_details:
            row_number = detail.row_context.get("rowNumber")
            if detail.duplicate_type is QualityRuleCode.CONFLICTING_DUPLICATE:
                self.record_quality_evaluation(
                    QualityEvaluation(
                        outcome=QualityOutcome.CONFLICTING_DUPLICATE,
                        violations=[
                            QualityViolation(
                                code=QualityRuleCode.CONFLICTING_DUPLICATE,
                                phase=QualityPhase.PERSISTENCE,
                                severity=QualitySeverity.ERROR,
                                outcome=QualityOutcome.CONFLICTING_DUPLICATE,
                                field="ingestion_key",
                                message="Duplicate key has a conflicting payload.",
                                actual=detail.incoming_fingerprint,
                                expected=detail.existing_fingerprint,
                                row=row_number,
                            )
                        ],
                        row_context=detail.row_context,
                    )
                )
            else:
                self.record_quality_evaluation(
                    QualityEvaluation(
                        outcome=QualityOutcome.EQUIVALENT_DUPLICATE,
                        violations=[
                            QualityViolation(
                                code=QualityRuleCode.EQUIVALENT_DUPLICATE,
                                phase=QualityPhase.PERSISTENCE,
                                severity=QualitySeverity.INFO,
                                outcome=QualityOutcome.EQUIVALENT_DUPLICATE,
                                field="ingestion_key",
                                message="Duplicate key has an equivalent payload.",
                                actual=detail.incoming_fingerprint,
                                expected=detail.existing_fingerprint,
                                row=row_number,
                            )
                        ],
                        row_context=detail.row_context,
                    )
                )
        self._record_batch_errors(result)

    def record_batch_metrics(self, metrics: dict[str, float | int]) -> None:
        """Store bounded aggregate timings for the file summary."""
        for key, value in metrics.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            numeric = max(0.0, float(value))
            if key in {"persistenceWindowMs", "slowestBatchMs"}:
                self.batch_metrics[key] = max(
                    float(self.batch_metrics.get(key, 0.0)), numeric
                )
            elif key == "dbWriteCount":
                self.batch_metrics[key] = int(self.batch_metrics.get(key, 0)) + int(value)
            else:
                self.batch_metrics[key] = float(self.batch_metrics.get(key, 0.0)) + numeric

    def record_persistence_failure(self) -> None:
        self.failed_rows += 1
        self.persistence_failed_rows += 1

    def record_quarantined(self, count: int) -> None:
        self.quarantined_rows += count

    @property
    def quality_counters(self) -> dict[str, int]:
        counters = self._row_counters()
        if self.equivalent_duplicate_rows:
            counters["equivalentDuplicateRows"] = self.equivalent_duplicate_rows
        if self.conflicting_duplicate_rows:
            counters["conflictingDuplicateRows"] = self.conflicting_duplicate_rows
        if self.warning_rows:
            counters["warningRows"] = self.warning_rows
        return counters

    @property
    def is_partial(self) -> bool:
        """Whether the run completed with row-level or persistence defects."""
        return bool(
            self.rejected_rows
            or self.persistence_failed_rows
            or self.quarantined_rows
        )

    @property
    def quality_summary(self) -> QualitySummary:
        return QualitySummary.from_counts(
            self.quality_rule_counts,
            self.quality_outcome_counts,
        )

    def _advance_quality_disposition(self, outcome: QualityOutcome) -> None:
        """Advance disposition monotonically without allocating per row."""

        if outcome is QualityOutcome.BATCH_FATAL:
            self.quality_decision = QualityDecision.FAIL
            self.orchestration_action = OrchestrationAction.FAIL
            return
        if self.quality_decision is QualityDecision.FAIL:
            return
        if outcome is QualityOutcome.CONFLICTING_DUPLICATE:
            self.quality_decision = QualityDecision.REVIEW
            self.orchestration_action = OrchestrationAction.HOLD_FOR_REVIEW
            return
        if outcome in {QualityOutcome.REJECT, QualityOutcome.WARNING}:
            self.quality_decision = QualityDecision.REVIEW

    def _row_counters(self) -> dict[str, int]:
        return {
            "inputRows": self.total_rows,
            "persistedRows": self.success_rows,
            "rejectedRows": self.rejected_rows,
            "duplicateRows": self.duplicate_rows,
            "failedRows": self.persistence_failed_rows,
            "persistenceFailedRows": self.persistence_failed_rows,
            "quarantinedRows": self.quarantined_rows,
        }

    @property
    def stage_summary(self) -> dict[str, Any]:
        return {
            "currentStage": self.current_stage,
            "stageDurationsMs": dict(self.stage_durations_ms),
            **self._row_counters(),
            "currentUnitKey": self.current_unit_key,
            "currentPage": self.current_page,
            "checkpointBefore": dict(self.checkpoint_before),
            "checkpointAfter": dict(self.checkpoint_after),
            "startedAt": self.started_at.isoformat(),
            "finishedAt": self.finished_at.isoformat() if self.finished_at else None,
            "durationMs": self.duration_ms,
            "wallClockMs": self.duration_ms,
            "batchMetrics": dict(self.batch_metrics),
            "errorCount": self.error_count,
            "errorSamplesDropped": self.error_samples_dropped,
            "lastErrorCode": self.last_error_code,
            "lastError": self.last_error,
            "quality": serialize_quality_summary(
                self.quality_summary,
                self.orchestration_action,
            ),
        }

    def _record_batch_errors(self, result: BatchWriteResult) -> None:
        if result.duplicates:
            self.add_error(
                {
                    "field": "transaction_duplicate",
                    "reason": (
                        f"{result.duplicates} transaction(s) skipped "
                        "because the ingestion key already exists"
                    ),
                }
            )
        if result.failed:
            self.add_error(
                {
                    "field": "batch_conflict",
                    "reason": (f"{result.failed} transaction(s) failed during batch persistence"),
                }
            )

    @property
    def stats(self) -> ProcessingStats:
        return ProcessingStats(
            total_rows=self.total_rows,
            success_rows=self.success_rows,
            failed_rows=self.failed_rows,
            duplicate_rows=self.duplicate_rows,
        )
