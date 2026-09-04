"""Compatibility entry point for the ingestion application flow."""

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any, Literal, Optional
from uuid import uuid4

from src.application.ingestion.contracts import (
    IngestionResult,
    ProcessFileCommand,
    serialize_quality_violation,
)
from src.application.ingestion.contracts import is_missing_ingestion_key_failure
from src.config.config_health import (
    ConfigurationApprovalRequiredError,
    record_config_run_health,
)
from src.config.loader import ConfigLoader, ConfigLoadError
from src.core.enums import ProcessingStatus
from src.core.utils import sanitize_runtime_error
from src.domain.ingestion.quality import (
    QualityEvaluation,
    QualityOutcome,
    QualityPhase,
    QualityRuleCode,
    QualitySeverity,
    quality_violation,
)
from src.domain.ingestion.ports import (
    IngestionFileRepository,
    IngestionQuarantineWriter,
    MappingConfigRepositoryPort,
    PartnerTransactionWriter,
)
from src.logging import StructuredLogger, get_structured_logger
from src.domain.ingestion.models import ReconciliationFile
from src.domain.mapping.models import MappingConfig
from src.pipeline.config_preparation import ConfigPreparationService
from src.pipeline.file_claim import FileClaimResult, FileClaimService
from src.pipeline.finalizer import IngestionRunFinalizer
from src.pipeline.metrics import IngestionPerformance
from src.pipeline.observability import IngestionStage
from src.pipeline.row_processor import RowProcessor
from src.pipeline.row_pipeline import (
    RowPipelineExecutor,
    RowPipelineRequest,
    RowPipelineResult,
)
from src.pipeline.quality_gate import (
    FileQualityGate,
    QualityGateFailure,
    SourceStructureUnreadableError,
)
from src.pipeline.run_state import IngestionRunState


@dataclass(frozen=True)
class _ClaimedFile:
    """Identity and claim data shared by the ingestion phases."""

    file_record: ReconciliationFile
    claim: FileClaimResult
    file_name: str
    file_hash: str
    fetch_unit_key: str | None
    run_id: str
    source_file_id: str


def _is_missing_ingestion_key_failure(state: IngestionRunState) -> bool:
    """Compatibility wrapper for callers using the legacy pipeline helper."""
    return is_missing_ingestion_key_failure(
        total_rows=state.total_rows,
        success_rows=state.success_rows,
        failed_rows=state.failed_rows,
        errors=[
            *state.errors,
            *({"field": field} for field in state.error_fields),
        ],
    )


class IngestionPipeline:
    """Orchestrates the full ingestion flow: file → config → normalize → validate → persist.

    Single entry point that wires all components together into a cohesive
    processing pipeline with batch insertion, per-row error handling,
    and accurate statistics tracking.
    """

    def __init__(
        self,
        db: Any,
        config_loader: ConfigLoader,
        batch_size: int | None = None,
        logger: StructuredLogger | None = None,
        fast_mode: bool = False,
        write_workers: int | None = None,
        ordered_insert: bool | None = None,
        file_repo: IngestionFileRepository | None = None,
        partner_repo: PartnerTransactionWriter | None = None,
        mapping_repo: MappingConfigRepositoryPort | None = None,
        quarantine_repo: IngestionQuarantineWriter | None = None,
    ) -> None:
        """Initialize the ingestion pipeline.

        Args:
            db: AsyncIOMotorDatabase instance.
            config_loader: ConfigLoader for loading mapping configurations.
            batch_size: Number of DataContainer objects to batch before inserting.
            logger: Optional StructuredLogger for lifecycle event emission.
            fast_mode: If True, bypass Pydantic model initialization for faster inserts.
            write_workers: Number of concurrent write workers/tasks.
            ordered_insert: Whether inserts must be ordered.
        """
        from src.config.settings import settings

        self._db = db
        self._config_loader = config_loader
        self._batch_size = batch_size if batch_size is not None else settings.ingest_batch_size
        self._write_workers = (
            write_workers if write_workers is not None else settings.ingest_write_workers
        )
        if self._write_workers < 1:
            raise ValueError("write_workers must be at least 1")
        self._ordered_insert = (
            ordered_insert if ordered_insert is not None else settings.ingest_ordered_insert
        )
        self._recon_repo = file_repo
        self._data_repo = partner_repo
        self._mapping_repo = mapping_repo
        self._quarantine_repo = quarantine_repo
        self._logger = logger or get_structured_logger()
        self._fast_mode = fast_mode
        self._file_claim = FileClaimService(db, file_repo)
        self._config_preparation = ConfigPreparationService(
            config_loader,
            mapping_repo,
            self._logger,
        )
        self._finalizer = IngestionRunFinalizer(self._logger)

    def _require_repository_ports(
        self,
        *,
        require_partner: bool = False,
        require_mapping: bool = False,
    ) -> None:
        """Fail fast when a pipeline was not assembled by a composition root."""
        missing: list[str] = []
        if self._recon_repo is None:
            missing.append("file_repo")
        if require_partner and self._data_repo is None:
            missing.append("partner_repo")
        if require_mapping and self._mapping_repo is None:
            missing.append("mapping_repo")
        if missing:
            missing_ports = ", ".join(missing)
            raise RuntimeError(
                "IngestionPipeline requires injected repository ports: "
                f"{missing_ports}. Use build_ingestion_pipeline() for production wiring."
            )

    def _require_file_repository(self) -> IngestionFileRepository:
        if self._recon_repo is None:
            raise RuntimeError("IngestionPipeline requires an injected file repository")
        return self._recon_repo

    def _require_partner_repository(self) -> PartnerTransactionWriter:
        if self._data_repo is None:
            raise RuntimeError("IngestionPipeline requires an injected partner repository")
        return self._data_repo

    def _require_mapping_repository(self) -> MappingConfigRepositoryPort:
        if self._mapping_repo is None:
            raise RuntimeError("IngestionPipeline requires an injected mapping repository")
        return self._mapping_repo

    async def _persist_stage_summary(
        self,
        file_record: ReconciliationFile | None,
        state: IngestionRunState,
    ) -> None:
        """Persist observability best-effort; it must not break ingestion."""
        if file_record is None:
            return
        file_record.stage_summary = state.stage_summary
        if self._recon_repo is None:
            return
        try:
            await self._recon_repo.update_stage_summary(file_record.id, state.stage_summary)
        except Exception:
            emitter = getattr(self._logger, "emit_ingestion_observability_write_failed", None)
            if emitter is not None:
                try:
                    emitter(
                        run_id=state.run_id,
                        source_file_id=str(file_record.id),
                        partner=state.partner,
                        stage=state.current_stage,
                    )
                except Exception:
                    pass

    def _emit_stage(
        self,
        stage: IngestionStage,
        *,
        run_id: str,
        source_file_id: str | None = None,
        error_code: str | None = None,
        state: IngestionRunState | None = None,
    ) -> None:
        if state is not None:
            state.set_source_context(
                run_id=run_id,
                source_file_id=source_file_id,
            )
            if error_code is not None:
                state.last_error_code = sanitize_runtime_error(error_code, max_length=96)
            state.begin_stage(stage.value)
        emitter = getattr(self._logger, "emit_ingestion_stage", None)
        if emitter is not None:
            try:
                emitter(
                    stage.value,
                    run_id,
                    source_file_id,
                    error_code,
                    partner=state.partner if state is not None else None,
                    source_unit_key=(state.current_unit_key if state is not None else None),
                    page=state.current_page if state is not None else None,
                    attempt=state.attempt if state is not None else 1,
                    checkpoint_before=(
                        state.checkpoint_before if state is not None else None
                    ),
                    checkpoint_after=(
                        state.checkpoint_after if state is not None else None
                    ),
                    error=state.last_error if state is not None else None,
                )
            except TypeError:
                # Keep lightweight legacy logger adapters source-compatible.
                emitter(stage.value, run_id, source_file_id, error_code)

    async def _compute_file_hash(self, file_path: str) -> str:
        """Compatibility seam for file hash tests and legacy callers."""
        service = getattr(self, "_file_claim", FileClaimService(None, None))
        return await service.compute_file_hash(file_path)

    def _derive_ingestion_key(self, txn: Any) -> str:
        """Derive a stable transaction key from normalized transaction data."""
        return RowProcessor.derive_ingestion_key(txn)

    def _derive_fetch_unit_key(
        self,
        *,
        partner: str,
        workflow_type: str,
        file_type: Any,
        reconciliation_date: Any,
        config_version: Optional[str],
        metadata: Optional[dict[str, Any]],
    ) -> Optional[str]:
        service = getattr(self, "_file_claim", FileClaimService(None, None))
        return service.derive_fetch_unit_key(
            partner=partner,
            workflow_type=workflow_type,
            file_type=file_type,
            reconciliation_date=reconciliation_date,
            config_version=config_version,
            metadata=metadata,
        )

    @staticmethod
    def _build_result(
        file_record: ReconciliationFile | None,
        state: IngestionRunState,
        *,
        outcome: Literal[
            "INGESTED",
            "PARTIAL",
            "FILE_DUPLICATE",
            "FETCH_UNIT_REPLAY",
            "WAITING_REVIEW",
            "FAILED",
        ] = "INGESTED",
        duplicate_code: str | None = None,
    ) -> IngestionResult:
        if outcome == "INGESTED" and state.is_partial:
            outcome = "PARTIAL"
        return IngestionResult(
            file_record=file_record,
            stats=state.stats,
            errors=state.errors,
            ingestion_keys=state.ingestion_keys,
            quality_counters=state.quality_counters,
            outcome=outcome,
            duplicate_code=duplicate_code,
            quality_decision=state.quality_decision,
            quality_summary=state.quality_summary,
            orchestration_action=state.orchestration_action,
            error_fields=set(state.error_fields),
        )

    def _evaluate_file_quality_gate(
        self,
        *,
        file_path: str,
        config: MappingConfig,
        state: IngestionRunState,
    ) -> QualityEvaluation:
        try:
            evaluation = FileQualityGate().evaluate(
                config,
                file_path=file_path if Path(file_path).exists() else None,
            )
        except SourceStructureUnreadableError as exc:
            violation = quality_violation(
                code=QualityRuleCode.SOURCE_STRUCTURE_UNREADABLE,
                phase=QualityPhase.FILE,
                severity=QualitySeverity.FATAL,
                outcome=QualityOutcome.BATCH_FATAL,
                field="_file",
                message=f"Unable to inspect source structure: {exc}",
                actual=str(exc),
            )
            evaluation = QualityEvaluation(
                outcome=QualityOutcome.BATCH_FATAL,
                violations=[violation],
            )
        self._record_quality_evaluation(state, evaluation)
        return evaluation

    @staticmethod
    def _record_quality_evaluation(
        state: IngestionRunState,
        evaluation: QualityEvaluation,
    ) -> None:
        state.record_quality_evaluation(evaluation)
        for violation in evaluation.violations:
            state.add_error(serialize_quality_violation(violation))

    def _log_performance(
        self,
        performance: IngestionPerformance,
    ) -> None:
        log_line = performance.to_log_line()
        if hasattr(self._logger, "get_logger"):
            self._logger.get_logger().info(log_line)
            return
        import logging

        logging.getLogger("reconciliation").info(log_line)

    async def execute(self, command: ProcessFileCommand) -> IngestionResult:
        """Execute ingestion through the application command boundary."""
        return await self._process_file(
            file_path=command.file_path,
            partner=command.partner,
            workflow_type=command.workflow_type,
            file_type=command.file_type,
            reconciliation_date=command.reconciliation_date,
            config_version=command.config_version,
            backfill_run_id=command.backfill_run_id,
            fetch_unit_metadata=command.fetch_unit_metadata,
            enable_config_health_check=command.enable_config_health_check,
            run_id=command.run_id,
            attempt=command.attempt,
        )

    async def process_file(
        self,
        file_path: str,
        partner: str,
        workflow_type: str,
        file_type: Any,
        reconciliation_date: Any,
        config_version: Optional[str] = None,
        backfill_run_id: str | None = None,
        fetch_unit_metadata: Optional[dict[str, Any]] = None,
        enable_config_health_check: bool = False,
        run_id: str | None = None,
        attempt: int = 1,
    ) -> IngestionResult:
        """Compatibility wrapper for callers using the legacy argument list."""
        return await self.execute(
            ProcessFileCommand(
                file_path=file_path,
                partner=partner,
                workflow_type=workflow_type,
                file_type=file_type,
                reconciliation_date=reconciliation_date,
                config_version=config_version,
                backfill_run_id=backfill_run_id,
                fetch_unit_metadata=fetch_unit_metadata,
                enable_config_health_check=enable_config_health_check,
                run_id=run_id,
                attempt=attempt,
            )
        )

    async def _claim_source_file(
        self,
        command: ProcessFileCommand,
        state: IngestionRunState,
    ) -> _ClaimedFile:
        self._emit_stage(
            IngestionStage.CLAIMING,
            run_id=state.run_id or "pending",
            state=state,
        )
        file_hash = await self._compute_file_hash(command.file_path)
        fetch_unit_key = self._derive_fetch_unit_key(
            partner=command.partner,
            workflow_type=command.workflow_type,
            file_type=command.file_type,
            reconciliation_date=command.reconciliation_date,
            config_version=command.config_version,
            metadata=command.fetch_unit_metadata,
        )
        file_name = Path(command.file_path).name
        claim = await self._file_claim.claim(
            file_path=command.file_path,
            partner=command.partner,
            workflow_type=command.workflow_type,
            file_type=command.file_type,
            reconciliation_date=command.reconciliation_date,
            config_version=command.config_version,
            fetch_unit_metadata=command.fetch_unit_metadata,
            file_hash=file_hash,
            fetch_unit_key=fetch_unit_key,
            repository=self._require_file_repository(),
        )
        file_record = claim.file_record
        run_id = state.run_id
        if not run_id or run_id == "pending":
            run_id = str(file_record.id)
        state.set_source_context(run_id=run_id, source_file_id=str(file_record.id))
        self._emit_stage(
            IngestionStage.CLAIMING,
            run_id=run_id,
            source_file_id=str(file_record.id),
            state=state,
        )
        return _ClaimedFile(
            file_record=file_record,
            claim=claim,
            file_name=file_name,
            file_hash=file_hash,
            fetch_unit_key=fetch_unit_key,
            run_id=run_id,
            source_file_id=str(file_record.id),
        )

    def _duplicate_result_if_any(
        self,
        claim: FileClaimResult,
        claimed: _ClaimedFile,
        state: IngestionRunState,
    ) -> IngestionResult | None:
        if claim.created:
            return None

        duplicate_code = claim.duplicate_code or "file_duplicate"
        self._emit_stage(
            IngestionStage.CLAIMING,
            run_id=claimed.run_id,
            source_file_id=claimed.source_file_id,
            error_code=duplicate_code,
            state=state,
        )
        self._logger.emit_file_failed(
            "duplicate",
            f"Duplicate ingestion claim ({duplicate_code})",
        )
        state.add_error(
            {
                "field": duplicate_code,
                "reason": (
                    "Fetch unit already processed"
                    if duplicate_code == "fetch_unit_duplicate"
                    else f"File already processed (hash: {claimed.file_hash[:16]}...)"
                ),
            }
        )
        return self._build_result(
            claimed.file_record,
            state,
            outcome=(
                "FETCH_UNIT_REPLAY"
                if duplicate_code == "fetch_unit_duplicate"
                else "FILE_DUPLICATE"
            ),
            duplicate_code=duplicate_code,
        )

    async def _prepare_mapping(
        self,
        command: ProcessFileCommand,
        claimed: _ClaimedFile,
        state: IngestionRunState,
    ) -> MappingConfig | None:
        self._emit_stage(
            IngestionStage.CONFIGURING,
            run_id=claimed.run_id,
            source_file_id=claimed.source_file_id,
            state=state,
        )
        try:
            return await self._config_preparation.prepare(
                file_path=command.file_path,
                file_name=claimed.file_name,
                partner=command.partner,
                workflow_type=command.workflow_type,
                file_type=command.file_type,
                reconciliation_date=command.reconciliation_date,
                config_version=command.config_version,
                source_file_id=claimed.source_file_id,
                enable_health_check=command.enable_config_health_check,
                backfill_run_id=command.backfill_run_id,
                mapping_repository=self._mapping_repo,
            )
        except ConfigurationApprovalRequiredError as approval_exc:
            self._emit_stage(
                IngestionStage.CONFIGURING,
                run_id=claimed.run_id,
                source_file_id=claimed.source_file_id,
                error_code="configuration_approval_required",
                state=state,
            )
            approval_reason = (
                f"configuration approval required for partner={command.partner}; "
                f"proposal_id={approval_exc.proposal_id or 'unknown'}; "
                f"action_id={approval_exc.action_id or 'unknown'}"
            )
            await self._require_file_repository().update_status(
                claimed.file_record.id, ProcessingStatus.PENDING
            )
            claimed.file_record.processing_status = ProcessingStatus.PENDING
            state.add_error({"field": "configApproval", "reason": approval_reason})
            return None
        except ConfigLoadError as config_exc:
            violations = [
                violation.model_copy(
                    update={
                        "phase": QualityPhase.CONFIGURATION,
                        "severity": QualitySeverity.FATAL,
                        "outcome": QualityOutcome.BATCH_FATAL,
                    }
                )
                for violation in config_exc.validation_errors
            ]
            if not violations:
                violations = [
                    quality_violation(
                        code=QualityRuleCode.CONFIG_VALIDATION,
                        phase=QualityPhase.CONFIGURATION,
                        severity=QualitySeverity.FATAL,
                        outcome=QualityOutcome.BATCH_FATAL,
                        field="_config",
                        message=config_exc.message,
                    )
                ]
            evaluation = QualityEvaluation(
                outcome=QualityOutcome.BATCH_FATAL,
                violations=violations,
            )
            self._record_quality_evaluation(state, evaluation)
            raise QualityGateFailure(violations) from config_exc

    async def _run_row_phase(
        self,
        command: ProcessFileCommand,
        config: MappingConfig,
        claimed: _ClaimedFile,
        state: IngestionRunState,
    ) -> RowPipelineResult:
        self._require_repository_ports(require_partner=True)
        self._emit_stage(
            IngestionStage.READING,
            run_id=claimed.run_id,
            source_file_id=claimed.source_file_id,
            state=state,
        )
        row_pipeline = RowPipelineExecutor(
            data_repository=self._require_partner_repository(),
            quarantine_repository=self._quarantine_repo,
            logger=self._logger,
            fast_mode=self._fast_mode,
            batch_size=self._batch_size,
            write_workers=self._write_workers,
            ordered_insert=self._ordered_insert,
        )
        return await row_pipeline.run(
            RowPipelineRequest(
                file_path=command.file_path,
                config=config,
                partner=command.partner,
                workflow_type=command.workflow_type,
                reconciliation_date=command.reconciliation_date,
                source_file_id=claimed.file_record.id,
                file_id=claimed.source_file_id,
                fetch_unit_key=claimed.fetch_unit_key,
                config_version=config.config_version or command.config_version,
                review_packet_id=(command.fetch_unit_metadata or {}).get("reviewPacketId"),
                post_approval_run_id=(command.fetch_unit_metadata or {}).get("postApprovalRunId"),
                state=state,
                emit_stage=lambda stage: self._emit_stage(
                    stage,
                    run_id=claimed.run_id,
                    source_file_id=claimed.source_file_id,
                    state=state,
                ),
            )
        )

    async def _finalize_success(
        self,
        command: ProcessFileCommand,
        claimed: _ClaimedFile,
        state: IngestionRunState,
        row_result: RowPipelineResult,
        started_at: float,
    ) -> None:
        post_start = time.perf_counter()
        state.record_batch_metrics(row_result.row_metrics.as_dict())
        self._emit_stage(
            IngestionStage.FINALIZING,
            run_id=claimed.run_id,
            source_file_id=claimed.source_file_id,
            state=state,
        )
        await self._finalizer.complete(
            self._require_file_repository(),
            claimed.file_record,
            state,
            (time.monotonic() - started_at) * 1000,
        )
        if command.enable_config_health_check:
            await record_config_run_health(
                config_repo=self._require_mapping_repository(),
                partner=command.partner,
                workflow_type=command.workflow_type,
                file_type=command.file_type,
                config_version=command.config_version,
                total_rows=state.total_rows,
                failed_rows=state.failed_rows,
            )
        performance = IngestionPerformance(
            total_ingest_ms=(time.monotonic() - started_at) * 1000,
            read_file_ms=row_result.read_file_ms,
            parse_rows_ms=row_result.row_metrics.parse_rows_ms,
            normalize_ms=row_result.row_metrics.normalize_ms,
            validate_ms=row_result.row_metrics.validate_ms,
            db_insert_ms=row_result.row_metrics.db_insert_ms,
            post_insert_update_ms=(time.perf_counter() - post_start) * 1000,
            records_count=state.total_rows,
            batch_size=self._batch_size,
            db_write_operation_count=row_result.row_metrics.db_write_count + 2,
            error_count=len(state.errors),
            slowest_batch_ms=row_result.row_metrics.slowest_batch_ms,
            wall_clock_ms=state.duration_ms or 0.0,
            total_batch_wall_ms=row_result.row_metrics.total_batch_wall_ms,
            persistence_window_ms=row_result.row_metrics.persistence_window_ms,
            mapping_ms=row_result.row_metrics.mapping_ms,
            copy_ms=row_result.row_metrics.copy_ms,
            insert_classify_ms=row_result.row_metrics.insert_classify_ms,
            transaction_overhead_ms=row_result.row_metrics.transaction_overhead_ms,
        )
        self._log_performance(performance)

    async def _process_file(
        self,
        file_path: str,
        partner: str,
        workflow_type: str,
        file_type: Any,  # FileType enum
        reconciliation_date: Any,  # datetime
        config_version: Optional[str] = None,
        backfill_run_id: str | None = None,
        fetch_unit_metadata: Optional[dict[str, Any]] = None,
        enable_config_health_check: bool = False,
        run_id: str | None = None,
        attempt: int = 1,
    ) -> IngestionResult:
        """Process an entire reconciliation file end-to-end.

        Flow:
        1. Compute identity and atomically claim the source file.
        2. Resolve mapping configuration and optional health approval.
        3. Delegate row processing to RowPipelineExecutor.
        4. Persist terminal status and return IngestionResult.

        On any exception: update status to FAILED, return partial stats.

        Args:
            file_path: Path to the input file.
            partner: Partner identifier.
            workflow_type: Workflow type string.
            file_type: FileType enum value.
            reconciliation_date: Date of the reconciliation file.
            config_version: Optional config version for load_by_version.
            enable_config_health_check: If True, check config freshness before
                processing and create approval proposals if file structure changed.

        Returns:
            IngestionResult with file_record, stats, and errors.
        """
        command = ProcessFileCommand(
            file_path=file_path,
            partner=partner,
            workflow_type=workflow_type,
            file_type=file_type,
            reconciliation_date=reconciliation_date,
            config_version=config_version,
            backfill_run_id=backfill_run_id,
            fetch_unit_metadata=fetch_unit_metadata,
            enable_config_health_check=enable_config_health_check,
            run_id=run_id,
            attempt=attempt,
        )
        self._require_repository_ports(require_mapping=command.enable_config_health_check)
        state = IngestionRunState(
            run_id=command.run_id or str(uuid4()),
            partner=command.partner,
            attempt=max(1, command.attempt),
        )
        metadata = command.fetch_unit_metadata or {}
        state.set_source_context(
            source_unit_key=metadata.get("sourceUnitKey") or metadata.get("source_unit_key"),
            page=metadata.get("page"),
            checkpoint_before=metadata.get("checkpointBefore"),
            checkpoint_after=metadata.get("checkpointAfter"),
        )
        file_record: ReconciliationFile | None = None

        try:
            started_at = time.monotonic()
            claimed = await self._claim_source_file(command, state)
            file_record = claimed.file_record
            duplicate_result = self._duplicate_result_if_any(
                claimed.claim,
                claimed,
                state,
            )
            if duplicate_result is not None:
                return duplicate_result

            await self._persist_stage_summary(file_record, state)
            self._logger.emit_file_started(
                claimed.source_file_id,
                claimed.file_name,
                command.partner,
            )
            config = await self._prepare_mapping(command, claimed, state)
            if config is None:
                state.finish_run()
                await self._persist_stage_summary(file_record, state)
                return self._build_result(file_record, state, outcome="WAITING_REVIEW")
            file_quality = self._evaluate_file_quality_gate(
                file_path=command.file_path,
                config=config,
                state=state,
            )
            if file_quality.decision.value == "FAIL":
                self._emit_stage(
                    IngestionStage.FINALIZING,
                    run_id=claimed.run_id,
                    source_file_id=claimed.source_file_id,
                    error_code=QualityOutcome.BATCH_FATAL.value,
                    state=state,
                )
                await self._finalizer.fail(
                    self._recon_repo,
                    claimed.file_record,
                    state,
                    QualityGateFailure(file_quality.violations),
                )
                return self._build_result(file_record, state, outcome="FAILED")
            row_result = await self._run_row_phase(command, config, claimed, state)
            if _is_missing_ingestion_key_failure(state):
                error = ValueError(
                    "Unable to derive ingestion_key: both id and trace are missing from the source rows."
                )
                self._emit_stage(
                    IngestionStage.FINALIZING,
                    run_id=claimed.run_id,
                    source_file_id=claimed.source_file_id,
                    error_code="ingestion_key_error",
                    state=state,
                )
                await self._finalizer.fail(
                    self._recon_repo,
                    claimed.file_record,
                    state,
                    error,
                )
                return self._build_result(
                    file_record,
                    state,
                    outcome="FAILED",
                )
            await self._finalize_success(command, claimed, state, row_result, started_at)
            return self._build_result(file_record, state)
        except Exception as exc:
            claimed_context = locals().get("claimed")
            run_id = (
                claimed_context.run_id if isinstance(claimed_context, _ClaimedFile) else "unknown"
            )
            source_file_id = (
                claimed_context.source_file_id
                if isinstance(claimed_context, _ClaimedFile)
                else None
            )
            self._emit_stage(
                IngestionStage.FINALIZING,
                run_id=run_id,
                source_file_id=source_file_id,
                error_code="ingestion_failed",
                state=state,
            )
            await self._finalizer.fail(self._recon_repo, file_record, state, exc)
            return self._build_result(file_record, state, outcome="FAILED")
