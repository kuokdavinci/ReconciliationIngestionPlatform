"""Execute the reader and row-processing phase of ingestion."""

from collections.abc import Callable
from dataclasses import dataclass
import time
from typing import Any

from src.domain.ingestion.ports import (
    IngestionQuarantineWriter,
    PartnerTransactionWriter,
)
from src.pipeline.batch_writer import BatchWriteCoordinator
from src.pipeline.observability import IngestionStage
from src.pipeline.row_batch_coordinator import (
    RowBatchContext,
    RowBatchCoordinator,
    RowBatchMetrics,
)
from src.pipeline.row_processor import RowProcessor
from src.pipeline.run_state import IngestionRunState
from src.normalizer.normalizer import TransactionNormalizer
from src.readers import create_reader
from src.validators.validator import Validator


@dataclass(frozen=True)
class RowPipelineRequest:
    """Runtime context required to process one claimed source file."""

    file_path: str
    config: Any
    partner: str
    workflow_type: str
    reconciliation_date: Any
    source_file_id: Any
    file_id: str
    fetch_unit_key: str | None
    config_version: str | None
    state: IngestionRunState
    emit_stage: Callable[[IngestionStage], None]
    review_packet_id: str | None = None
    post_approval_run_id: str | None = None


@dataclass(frozen=True)
class RowPipelineResult:
    """Timing and row metrics produced by the processing phase."""

    read_file_ms: float
    row_metrics: RowBatchMetrics


class RowPipelineExecutor:
    """Build and run row-processing collaborators for one source file."""

    def __init__(
        self,
        *,
        data_repository: PartnerTransactionWriter,
        quarantine_repository: IngestionQuarantineWriter | None,
        logger: Any,
        fast_mode: bool,
        batch_size: int,
        write_workers: int,
        ordered_insert: bool,
    ) -> None:
        self._data_repository = data_repository
        self._quarantine_repository = quarantine_repository
        self._logger = logger
        self._fast_mode = fast_mode
        self._batch_size = batch_size
        self._write_workers = write_workers
        self._ordered_insert = ordered_insert

    async def run(self, request: RowPipelineRequest) -> RowPipelineResult:
        """Read, transform, validate and persist all rows for a file."""
        started = time.perf_counter()
        with create_reader(request.file_path, request.config) as reader:
            read_file_ms = (time.perf_counter() - started) * 1000
            row_processor = self._build_row_processor(request)
            batch_writer = BatchWriteCoordinator(
                self._data_repository,
                workers=self._write_workers,
                ordered=self._ordered_insert,
            )
            row_metrics = await RowBatchCoordinator(
                reader=reader,
                start_row=request.config.start_row,
                row_processor=row_processor,
                batch_writer=batch_writer,
                state=request.state,
                batch_size=self._batch_size,
                logger=self._logger,
                context=RowBatchContext(
                    file_id=request.file_id,
                    partner=request.partner,
                    reconciliation_date=request.reconciliation_date,
                    fetch_unit_key=request.fetch_unit_key,
                    config_version=request.config_version,
                    review_packet_id=request.review_packet_id,
                    post_approval_run_id=request.post_approval_run_id,
                ),
                quarantine_repo=self._quarantine_repository,
                emit_stage=request.emit_stage,
            ).run()
        return RowPipelineResult(read_file_ms=read_file_ms, row_metrics=row_metrics)

    def _build_row_processor(self, request: RowPipelineRequest) -> RowProcessor:
        normalizer = TransactionNormalizer(request.config.field_mappings)
        # Duplicate authority belongs to the atomic database write. Keeping
        # validation here side-effect free also prevents one lookup per row.
        validator = Validator()
        return RowProcessor(
            normalizer=normalizer,
            validator=validator,
            fast_mode=self._fast_mode,
            partner=request.partner,
            workflow_type=request.workflow_type,
            reconciliation_date=request.reconciliation_date,
            source_file_id=request.source_file_id,
        )
