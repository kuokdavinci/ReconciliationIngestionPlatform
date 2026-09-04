"""Lifecycle persistence for ingestion runs."""

from src.core.enums import ProcessingStatus
from src.domain.ingestion.models import ReconciliationFile
from src.domain.ingestion.ports import IngestionFileRepository
from src.logging import StructuredLogger
from src.pipeline.run_state import IngestionRunState


class IngestionRunFinalizer:
    """Persist terminal run state and emit terminal lifecycle events."""

    def __init__(self, logger: StructuredLogger) -> None:
        self._logger = logger

    async def complete(
        self,
        repository: IngestionFileRepository,
        file_record: ReconciliationFile,
        state: IngestionRunState,
        duration_ms: float,
    ) -> None:
        state.finish_run()
        status = ProcessingStatus.PARTIAL if state.is_partial else ProcessingStatus.COMPLETED
        await repository.update_processing_stats(
            file_record.id,
            state.total_rows,
            state.success_rows,
            state.failed_rows,
            state.duplicate_rows,
        )
        await repository.update_status(file_record.id, status)
        try:
            await repository.update_stage_summary(file_record.id, state.stage_summary)
        except Exception:
            self._warn_observability_write_failed(state, file_record)
        self._apply_stats(file_record, state, status)
        self._logger.emit_file_completed(
            str(file_record.id),
            state.total_rows,
            state.success_rows,
            state.failed_rows,
            duration_ms,
        )

    async def fail(
        self,
        repository: IngestionFileRepository | None,
        file_record: ReconciliationFile | None,
        state: IngestionRunState,
        error: Exception,
    ) -> None:
        state.record_error(error, state.last_error_code or "ingestion_failed")
        state.finish_run()
        self._logger.emit_file_failed(
            str(file_record.id) if file_record else "unknown",
            state.last_error or "Unexpected runtime error.",
        )
        if file_record is not None and repository is not None:
            try:
                await repository.update_processing_stats(
                    file_record.id,
                    state.total_rows,
                    state.success_rows,
                    state.failed_rows,
                    state.duplicate_rows,
                )
                await repository.update_status(file_record.id, ProcessingStatus.FAILED)
                self._apply_stats(file_record, state, ProcessingStatus.FAILED)
            except Exception:
                pass
        if file_record is not None and repository is not None:
            try:
                await repository.update_stage_summary(file_record.id, state.stage_summary)
            except Exception:
                self._warn_observability_write_failed(state, file_record)
        state.add_error({"field": "ingestion_error", "reason": state.last_error})

    @staticmethod
    def _apply_stats(
        file_record: ReconciliationFile,
        state: IngestionRunState,
        status: ProcessingStatus,
    ) -> None:
        file_record.processing_status = status
        file_record.total_rows = state.total_rows
        file_record.success_rows = state.success_rows
        file_record.failed_rows = state.failed_rows
        file_record.duplicate_rows = state.duplicate_rows
        file_record.stage_summary = state.stage_summary

    def _warn_observability_write_failed(
        self,
        state: IngestionRunState,
        file_record: ReconciliationFile,
    ) -> None:
        emitter = getattr(self._logger, "emit_ingestion_observability_write_failed", None)
        if emitter is None:
            return
        try:
            emitter(
                run_id=state.run_id,
                source_file_id=str(file_record.id),
                partner=state.partner or getattr(file_record, "partner", None),
                stage=state.current_stage,
            )
        except Exception:
            pass
