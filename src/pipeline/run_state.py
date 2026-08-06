"""Mutable state for one ingestion run."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
import time
from typing import Any

from src.core.types import BatchInsertResult, ProcessingStats


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
        errors: list[dict[str, Any]],
    ) -> None:
        self.failed_rows += 1
        self.rejected_rows += 1
        self.errors.extend(errors)

    def record_valid_row(self, ingestion_key: str | None) -> None:
        self.ingestion_keys.append(ingestion_key or "")

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

    def record_batch_result(self, result: int | BatchInsertResult) -> None:
        if isinstance(result, BatchInsertResult):
            self.success_rows += result.inserted
            self.duplicate_rows += result.duplicates
            self.failed_rows += result.failed
            self.persistence_failed_rows += result.failed
            self._record_batch_errors(result)
            return

        self.success_rows += int(result)

    def record_persistence_failure(self) -> None:
        self.persistence_failed_rows += 1

    def record_quarantined(self, count: int) -> None:
        self.quarantined_rows += count

    @property
    def quality_counters(self) -> dict[str, int]:
        return self._row_counters()

    def _row_counters(self) -> dict[str, int]:
        return {
            "inputRows": self.total_rows,
            "persistedRows": self.success_rows,
            "rejectedRows": self.rejected_rows,
            "duplicateRows": self.duplicate_rows,
            "failedRows": self.persistence_failed_rows,
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
        }

    def _record_batch_errors(self, result: BatchInsertResult) -> None:
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
                    "reason": (
                        f"{result.failed} transaction(s) failed "
                        "during batch persistence"
                    ),
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
