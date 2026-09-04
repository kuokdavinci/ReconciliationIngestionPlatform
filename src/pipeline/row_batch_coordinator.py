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
    total_batch_wall_ms: float = 0.0
    persistence_window_ms: float = 0.0
    mapping_ms: float = 0.0
    copy_ms: float = 0.0
    insert_classify_ms: float = 0.0
    transaction_overhead_ms: float = 0.0
    stage_setup_ms: float = 0.0
    tuple_materialization_ms: float = 0.0

    def record_batch_result(self, result: BatchWriteResult) -> None:
        """Aggregate optional repository timings without changing row accounting."""
        timings = result.timings_ms
        self.total_batch_wall_ms += max(0.0, float(timings.get("batch_wall_ms", 0.0)))
        self.mapping_ms += max(0.0, float(timings.get("mapping_ms", 0.0)))
        self.copy_ms += max(0.0, float(timings.get("copy_ms", 0.0)))
        self.insert_classify_ms += max(
            0.0, float(timings.get("insert_classify_ms", 0.0))
        )
        self.transaction_overhead_ms += max(
            0.0, float(timings.get("transaction_overhead_ms", 0.0))
        )
        self.stage_setup_ms += max(0.0, float(timings.get("stage_setup_ms", 0.0)))
        self.tuple_materialization_ms += max(
            0.0, float(timings.get("tuple_materialization_ms", 0.0))
        )

    def as_dict(self) -> dict[str, float | int]:
        return {
            "parseRowsMs": self.parse_rows_ms,
            "normalizeMs": self.normalize_ms,
            "validateMs": self.validate_ms,
            "totalBatchWallMs": self.total_batch_wall_ms,
            "persistenceWindowMs": self.persistence_window_ms,
            "mappingMs": self.mapping_ms,
            "copyMs": self.copy_ms,
            "insertClassifyMs": self.insert_classify_ms,
            "transactionOverheadMs": self.transaction_overhead_ms,
            "stageSetupMs": self.stage_setup_ms,
            "tupleMaterializationMs": self.tuple_materialization_ms,
            "dbWriteCount": self.db_write_count,
            "slowestBatchMs": self.slowest_batch_ms,
        }


@dataclass(frozen=True)
class RowBatchContext:
    """File metadata needed while logging and quarantining processed rows."""

    file_id: str
    partner: str
    reconciliation_date: Any
    fetch_unit_key: str | None
    config_version: str | None
    review_packet_id: str | None = None
    post_approval_run_id: str | None = None


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
                if self._state.should_log_row_error():
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
            self._record_batch_result(result, metrics)
            await self._quarantine_conflicts(result)
        if quarantine_buffer:
            await self._flush_quarantine(quarantine_buffer)
        if db_start_wall > 0.0:
            metrics.db_insert_ms = (db_end_wall - db_start_wall) * 1000
            metrics.persistence_window_ms = metrics.db_insert_ms
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
                self._record_batch_result(result, metrics)
                await self._quarantine_conflicts(result)
        return db_start_wall, db_end_wall

    def _record_batch_result(
        self,
        result: BatchWriteResult,
        metrics: RowBatchMetrics,
    ) -> None:
        self._state.record_batch_result(result)
        metrics.record_batch_result(result)

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
                    sourceFileId=self._context.file_id,
                    sourceUnitKey=self._context.fetch_unit_key,
                    reviewPacketId=self._context.review_packet_id,
                    postApprovalRunId=self._context.post_approval_run_id,
                    partner=self._context.partner,
                    reconciliationDate=self._context.reconciliation_date,
                    rowNumber=row_number,
                    rawRow=raw_row,
                    ingestionKey=detail.ingestion_key,
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
                    configVersion=self._context.config_version,
                    incomingFingerprint=incoming,
                    existingFingerprint=existing,
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
            sourceFileId=self._context.file_id,
            sourceUnitKey=self._context.fetch_unit_key,
            reviewPacketId=self._context.review_packet_id,
            postApprovalRunId=self._context.post_approval_run_id,
            partner=self._context.partner,
            reconciliationDate=self._context.reconciliation_date,
            rowNumber=row_number,
            rawRow=sanitize_raw_row(row_tuple),
            errors=errors,
            phase=QuarantinePhase.VALIDATION,
            configVersion=self._context.config_version,
        )
