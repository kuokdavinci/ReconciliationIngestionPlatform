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
    stage_durations_ms: dict[str, float] = field(default_factory=dict)
    _stage_started_at: float | None = field(default=None, repr=False)

    def record_row(self) -> int:
        self.total_rows += 1
        return self.total_rows

    def record_invalid_row(
        self,
        errors: list[dict[str, Any]] | list[QualityViolation],
    ) -> None:
        self.failed_rows += 1
        self.rejected_rows += 1
        self.errors.extend(
            serialize_quality_violation(item) if isinstance(item, QualityViolation) else item
            for item in errors
        )

    def record_valid_row(self, ingestion_key: str | None) -> None:
        self.ingestion_keys.append(ingestion_key or "")

    def record_row_outcome(self, outcome: Any) -> None:
        """Record one row outcome and update bounded quality aggregates."""

        if outcome.is_valid:
            self.record_valid_row(outcome.ingestion_key)
            if outcome.outcome is QualityOutcome.WARNING:
                self.errors.extend(
                    serialize_quality_violation(violation) for violation in outcome.violations
                )
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
        self.errors.append(error)

    def begin_stage(self, stage: str) -> None:
        self.finish_stage()
        self.current_stage = stage
        self._stage_started_at = time.perf_counter()

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

    def record_error(self, error: Exception) -> None:
        self.last_error = str(error)

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
            **self._row_counters(),
            "currentStage": self.current_stage,
            "stageDurationsMs": dict(self.stage_durations_ms),
            "startedAt": self.started_at.isoformat(),
            "finishedAt": self.finished_at.isoformat() if self.finished_at else None,
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
