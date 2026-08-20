"""Coordinate row processing, batch persistence and quarantine writes."""

from dataclasses import dataclass
import time
from collections.abc import Callable
from typing import Any

from src.domain.ingestion.ports import IngestionQuarantineWriter
from src.domain.ingestion.quarantine import (
    IngestionQuarantineRecord,
    QuarantinePhase,
    sanitize_raw_row,
)
from src.domain.ingestion.quality import QualityRuleCode
from src.domain.partner_transaction.duplicates import BatchWriteResult
from src.pipeline.batch_writer import BatchWriteCoordinator
from src.pipeline.observability import IngestionStage
from src.pipeline.row_processor import RowProcessor
from src.pipeline.run_state import IngestionRunState


@dataclass
class RowBatchMetrics:
    """Performance counters produced by one row/batch execution."""

    parse_rows_ms: float = 0.0
    normalize_ms: float = 0.0
    validate_ms: float = 0.0
    db_insert_ms: float = 0.0
    db_write_count: int = 0
    slowest_batch_ms: float = 0.0


@dataclass(frozen=True)
class RowBatchContext:
    """File metadata needed while logging and quarantining processed rows."""

    file_id: str
    partner: str
    reconciliation_date: Any
    fetch_unit_key: str | None
    config_version: str | None


async def flush_quarantine_records(
    records: list[IngestionQuarantineRecord],
    *,
    repository: IngestionQuarantineWriter | None,
    state: IngestionRunState,
    emit_stage: Callable[[IngestionStage], None],
) -> None:
    """Persist a quarantine batch and update its accounting."""
    if repository is None:
        return
    emit_stage(IngestionStage.QUARANTINING)
    persisted = await repository.create_many(records)
    state.record_quarantined(persisted)


class RowBatchCoordinator:
    """Run the row loop without owning file claims or terminal lifecycle."""

    def __init__(
        self,
        *,
        reader: Any,
        start_row: int,
        row_processor: RowProcessor,
        batch_writer: BatchWriteCoordinator,
        state: IngestionRunState,
        batch_size: int,
        logger: Any,
        context: RowBatchContext,
        quarantine_repo: IngestionQuarantineWriter | None,
        emit_stage: Callable[[IngestionStage], None],
    ) -> None:
        self._reader = reader
        self._start_row = start_row
        self._row_processor = row_processor
        self._batch_writer = batch_writer
        self._state = state
        self._batch_size = batch_size
        self._logger = logger
        self._context = context
        self._quarantine_repo = quarantine_repo
        self._emit_stage = emit_stage

    async def run(self) -> RowBatchMetrics:
        """Process all rows, flush pending batches and persist quarantine rows."""
        metrics = RowBatchMetrics()
        quarantine_buffer: list[IngestionQuarantineRecord] = []
        batch_buffer: list[Any] = []
        batch_context_buffer: list[dict[str, Any]] = []
        db_start_wall = 0.0
        db_end_wall = 0.0

        self._emit_stage(IngestionStage.PROCESSING)
        row_iterator = iter(self._reader.iter_rows())
        while True:
            parse_started = time.perf_counter()
            try:
                row_tuple = next(row_iterator)
            except StopIteration:
                break
            metrics.parse_rows_ms += (time.perf_counter() - parse_started) * 1000
            row_number = self._start_row + self._state.record_row() - 1
            row_result = self._row_processor.process(row_tuple, row_number)
            metrics.normalize_ms += row_result.normalize_ms
            metrics.validate_ms += row_result.validate_ms

            self._state.record_row_outcome(row_result)
            if not row_result.is_valid:
                if self._quarantine_repo is not None:
                    quarantine_buffer.append(
                        self._quarantine_record(row_tuple, row_number, row_result.errors)
                    )
                    if len(quarantine_buffer) >= self._batch_size:
                        await self._flush_quarantine(quarantine_buffer)
                        quarantine_buffer = []
                self._logger.emit_row_failed(
                    self._context.file_id,
                    row_number,
                    row_result.failure_trace or f"row:{row_number}",
                    row_result.failure_reason or "Row processing failed",
                )
                continue

            batch_buffer.append(row_result.data_container)
            batch_context_buffer.append(
                {
                    "rowNumber": row_number,
                    "rawRow": row_tuple,
                }
            )
            if len(batch_buffer) >= self._batch_size:
                db_start_wall, db_end_wall = await self._flush_batch(
                    batch_buffer,
                    batch_context_buffer,
                    metrics,
                    db_start_wall,
                    db_end_wall,
                )
                batch_buffer = []
                batch_context_buffer = []

        if batch_buffer:
            db_start_wall, db_end_wall = await self._flush_batch(
                batch_buffer,
                batch_context_buffer,
                metrics,
                db_start_wall,
                db_end_wall,
            )

        pending_results = await self._batch_writer.drain()
        if pending_results:
            db_end_wall = time.perf_counter()
        for result in pending_results:
            self._state.record_batch_result(result)
            await self._quarantine_conflicts(result)
        if quarantine_buffer:
            await self._flush_quarantine(quarantine_buffer)
        if db_start_wall > 0.0:
            metrics.db_insert_ms = (db_end_wall - db_start_wall) * 1000
        return metrics

    async def _flush_batch(
        self,
        batch: list[Any],
        row_contexts: list[dict[str, Any]],
        metrics: RowBatchMetrics,
        db_start_wall: float,
        db_end_wall: float,
    ) -> tuple[float, float]:
        started = time.perf_counter()
        if db_start_wall == 0.0:
            db_start_wall = started
        self._emit_stage(IngestionStage.PERSISTING)
        results = await self._batch_writer.submit(batch, row_contexts=row_contexts)
        duration_ms = (time.perf_counter() - started) * 1000
        metrics.slowest_batch_ms = max(metrics.slowest_batch_ms, duration_ms)
        metrics.db_write_count += 1
        if results:
            db_end_wall = time.perf_counter()
            for result in results:
                self._state.record_batch_result(result)
                await self._quarantine_conflicts(result)
        return db_start_wall, db_end_wall

    async def _quarantine_conflicts(self, result: BatchWriteResult) -> None:
        if self._quarantine_repo is None or not result.duplicate_details:
            return
        records: list[IngestionQuarantineRecord] = []
        for detail in result.duplicate_details:
            if detail.duplicate_type is not QualityRuleCode.CONFLICTING_DUPLICATE:
                continue
            context = detail.row_context
            row_number = context.get("rowNumber")
            incoming = detail.incoming_fingerprint
            existing = detail.existing_fingerprint
            raw_row = sanitize_raw_row(context.get("rawRow", {}))
            records.append(
                IngestionQuarantineRecord(
                    source_file_id=self._context.file_id,
                    source_unit_key=self._context.fetch_unit_key,
                    partner=self._context.partner,
                    reconciliation_date=self._context.reconciliation_date,
                    row_number=row_number,
                    raw_row=raw_row,
                    errors=[
                        {
                            "field": "ingestion_key",
                            "reason": "Duplicate key has a conflicting payload.",
                            "errorCode": QualityRuleCode.CONFLICTING_DUPLICATE.value,
                            "phase": "PERSISTENCE",
                            "severity": "ERROR",
                            "outcome": QualityRuleCode.CONFLICTING_DUPLICATE.value,
                            "incomingFingerprint": incoming,
                            "existingFingerprint": existing,
                            "sourceFileId": self._context.file_id,
                            "sourceUnitKey": self._context.fetch_unit_key,
                            "rowNumber": row_number,
                            "rawRow": raw_row,
                            "configVersion": self._context.config_version,
                        }
                    ],
                    phase=QuarantinePhase.BATCH,
                    config_version=self._context.config_version,
                    incoming_fingerprint=incoming,
                    existing_fingerprint=existing,
                )
            )
        if records:
            await self._flush_quarantine(records)

    async def _flush_quarantine(self, records: list[IngestionQuarantineRecord]) -> None:
        await flush_quarantine_records(
            records,
            repository=self._quarantine_repo,
            state=self._state,
            emit_stage=self._emit_stage,
        )

    def _quarantine_record(
        self,
        row_tuple: tuple[Any, ...],
        row_number: int,
        errors: list[dict[str, Any]],
    ) -> IngestionQuarantineRecord:
        return IngestionQuarantineRecord(
            source_file_id=self._context.file_id,
            source_unit_key=self._context.fetch_unit_key,
            partner=self._context.partner,
            reconciliation_date=self._context.reconciliation_date,
            row_number=row_number,
            raw_row=sanitize_raw_row(row_tuple),
            errors=errors,
            phase=QuarantinePhase.VALIDATION,
            config_version=self._context.config_version,
        )
