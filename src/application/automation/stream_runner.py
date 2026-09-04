"""Public dispatcher for one configured source stream."""

from datetime import datetime
from typing import Any, Optional

from src.application.automation.file_stream_runner import run_file_stream
from src.application.automation.paginated_stream_runner import run_paginated_stream
from src.application.automation.stream_failure import unexpected_failure_result
from src.application.automation.stream_runtime import checkpoint_result
from src.application.automation.stream_identity import (
    raw_stage_key as build_raw_stage_key,
    stream_identity,
)
from src.application.automation.stream_ingestion import (
    build_source_unit_ingestor,
    cleanup_source_unit,
    ingestion_error_result,
)
from src.application.automation.stream_lifecycle import (
    StreamLifecycle,
    StreamLifecycleDependencies,
    StreamRunContext,
    StreamRunnerDependencies,
    checkpoint_short_circuit_result,
    empty_stream_stats,
)
from src.application.automation.stream_runtime import (
    create_stream_review_packet,
    evaluate_stream_mapping,
)
from src.application.automation.stream_runtime import (
    finish_source_stream_run,
    runtime_attempt_event,
    stage_stream_unit,
)
from src.application.ingestion.source_unit_orchestrator import process_source_units
from src.application.runtime.service import create_runtime_run, update_runtime_run
from src.core.utils import summarize_runtime_error
from src.domain.fetch_config.models import FetchConfig, FetchMethod
from src.domain.ingestion.checkpoints import IngestionMode
from src.domain.ingestion.retry_policy import RetryPolicy
from src.domain.ingestion.source_units import SourceUnitMetadata
from src.pipeline.observability import IngestionStage
from src.pipeline.run_state import IngestionRunState
from src.fetchers import create_fetcher
from src.infrastructure.ingestion.checkpoint_repository import IngestionCheckpointRepository
from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository
from src.infrastructure.ingestion.raw_page_repository import RawIngestionPageRepository
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.infrastructure.runtime.repository import PartnerRuntimeRunRepository
from src.logging import StructuredLogger, get_structured_logger


def _checkpoint_context(checkpoint: Any) -> dict[str, Any]:
    if checkpoint is None:
        return {}
    return {
        "status": getattr(getattr(checkpoint, "status", None), "value", getattr(checkpoint, "status", None)),
        "currentUnitKey": getattr(checkpoint, "current_unit_key", None),
        "lastCompletedUnitKey": getattr(checkpoint, "last_completed_unit_key", None),
        "cursorBefore": getattr(checkpoint, "cursor_before", None),
        "cursorAfter": getattr(checkpoint, "cursor_after", None),
    }


def _runtime_event_result(
    result: Any,
    *,
    unit: SourceUnitMetadata | None = None,
    checkpoint: Any = None,
) -> dict[str, Any]:
    payload = dict(result) if isinstance(result, dict) else {}
    if unit is not None:
        payload.setdefault("sourceUnitKey", unit.source_unit_key)
        payload.setdefault("currentPage", unit.page)
    payload.setdefault("checkpointAfter", _checkpoint_context(checkpoint))
    summary = payload.get("stageSummary") or {}
    if isinstance(summary, dict):
        payload.setdefault("stage", summary.get("currentStage"))
        payload.setdefault("durationMs", summary.get("durationMs"))
    return payload


async def _persist_runtime_observation(
    db: Any,
    run: Any,
    state: IngestionRunState,
    *,
    status: str,
    result: Any = None,
    unit: SourceUnitMetadata | None = None,
    checkpoint: Any = None,
    message: str | None = None,
) -> None:
    """Persist a bounded runtime observation without affecting ingestion."""
    payload = _runtime_event_result(result, unit=unit, checkpoint=checkpoint)
    payload.setdefault("checkpointBefore", state.checkpoint_before)
    summary = payload.get("stageSummary")
    if isinstance(summary, dict):
        state.merge_stage_summary(summary)
    if payload.get("error") or payload.get("errorCode"):
        error_value = payload.get("error") or payload.get("errorCode")
        error_code = payload.get("errorCode")
        state.record_error(
            str(error_value),
            str(error_code) if error_code is not None else None,
        )
    if unit is not None:
        state.set_source_context(
            source_unit_key=unit.source_unit_key,
            page=unit.page,
            checkpoint_before=payload.get("checkpointBefore"),
            checkpoint_after=payload.get("checkpointAfter"),
        )
    source_file_id = payload.get("sourceFileId")
    if source_file_id is not None:
        state.set_source_context(source_file_id=str(source_file_id))
    try:
        event = runtime_attempt_event(
            run,
            status,
            result=payload,
            message=message,
            stage=state.current_stage,
            source_unit_key=state.current_unit_key,
            page=state.current_page,
            duration_ms=payload.get("durationMs"),
            attempt=state.attempt,
        )
        await update_runtime_run(
            db,
            str(run.id),
            status=None,
            stage_summary=state.stage_summary,
            attempt_event=event,
        )
    except Exception:
        get_structured_logger().emit_ingestion_observability_write_failed(
            run_id=state.run_id,
            source_file_id=state.source_file_id,
            partner=state.partner,
            stage=state.current_stage,
        )


def select_stream_runner(config: FetchConfig) -> Any:
    """Select the mode-specific runner while keeping the public dispatcher thin."""

    if config.fetch_method == FetchMethod.API and config.get_method_config().pagination:
        return run_paginated_stream
    return run_file_stream


async def run_source_stream(
    config: FetchConfig,
    db: Any,
    config_loader: Any,
    reconciliation_date: datetime,
    batch_size: int = 100,
    structured_logger: Optional[StructuredLogger] = None,
    mode: IngestionMode = IngestionMode.SCHEDULED,
    runtime_run_id: str | None = None,
    orchestration: dict[str, Any] | None = None,
    mapping_config_version: str | None = None,
    backfill_run_id: str | None = None,
    raise_on_unexpected: bool = False,
) -> dict[str, Any]:
    """Run one source stream sequentially from its checkpoint boundary."""

    lifecycle = StreamLifecycle(
        db=db,
        config=config,
        reconciliation_date=reconciliation_date,
        runtime_run_id=runtime_run_id,
        orchestration=orchestration,
        dependencies=StreamLifecycleDependencies(
            create_runtime_run=create_runtime_run,
            update_runtime_run=update_runtime_run,
            runtime_run_repository=PartnerRuntimeRunRepository,
            finish_source_stream_run=finish_source_stream_run,
            runtime_attempt_event=runtime_attempt_event,
        ),
    )
    run = await lifecycle.start()
    runtime_state = IngestionRunState(
        run_id=str(run.id),
        partner=config.partner,
        attempt=max(
            1,
            int(
                getattr(
                    getattr(run, "orchestration", None),
                    "try_number",
                    (orchestration or {}).get("tryNumber", 1),
                )
            ),
        ),
    )
    runtime_state.begin_stage(IngestionStage.CLAIMING.value)
    lifecycle.attach_runtime_state(runtime_state)
    await _persist_runtime_observation(
        db,
        run,
        runtime_state,
        status="STARTED",
        result={"stage": IngestionStage.CLAIMING.value},
        message="Source stream runtime started.",
    )
    identity = stream_identity(
        config,
        mode=mode,
        reconciliation_date=reconciliation_date,
    )
    identity.update(
        {
            "runtimeRunId": str(run.id),
            "attempt": runtime_state.attempt,
        }
    )
    checkpoint_repo = IngestionCheckpointRepository(db)
    checkpoint = await checkpoint_repo.find_by_stream(
        partner=identity["partner"],
        fetch_config_id=identity["fetchConfigId"],
        source_type=identity["sourceType"],
        stream_key=identity["streamKey"],
        mode=mode,
    )
    short_circuit = checkpoint_short_circuit_result(checkpoint)
    if short_circuit is not None:
        return await lifecycle.finish(short_circuit, empty_stream_stats())

    stage_key = (
        build_raw_stage_key(config, reconciliation_date)
        if config.fetch_method == FetchMethod.API
        else None
    )
    if stage_key is not None:
        try:
            completed_file = await ReconciliationFileRepository(
                db
            ).find_completed_by_raw_stage_key(stage_key)
        except (AttributeError, TypeError):
            # Lightweight test doubles and legacy adapters may not expose an
            # awaitable Mongo collection. The normal stream path remains safe.
            completed_file = None
        if completed_file is not None:
            return await lifecycle.finish(
                {
                    "success": True,
                    "processed": 0,
                    "failed": 0,
                    "reconciliationSkipped": True,
                    "streamAlreadyCompleted": True,
                    "checkpoint": checkpoint_result(checkpoint)
                    if checkpoint is not None
                    else None,
                },
                empty_stream_stats(),
            )

    fetcher = create_fetcher(config)

    async def cleanup_unit(unit: SourceUnitMetadata) -> None:
        await cleanup_source_unit(config, unit)

    ingest_unit, stats = build_source_unit_ingestor(
        config=config,
        db=db,
        config_loader=config_loader,
        partner=config.partner,
        reconciliation_date=reconciliation_date,
        batch_size=batch_size,
        structured_logger=structured_logger,
        reconciliation_run_id=str(run.id),
        mapping_config_version=mapping_config_version,
        backfill_run_id=backfill_run_id,
        attempt=runtime_state.attempt,
        # A backfill compares the pinned config with each day's source
        # structure. Equivalent days return the same approved config; a drift
        # day raises a review outcome and releases its checkpoint.
        config_health_check_enabled=True,
    )
    retry_policy = RetryPolicy()
    raw_page_repo = RawIngestionPageRepository(db)
    runtime_state.begin_stage(IngestionStage.READING.value)
    await lifecycle.mark_ingesting()

    async def observe_unit_started(unit: SourceUnitMetadata, checkpoint: Any) -> None:
        runtime_state.begin_stage(IngestionStage.READING.value)
        runtime_state.set_source_context(
            source_unit_key=unit.source_unit_key,
            page=unit.page,
            checkpoint_before={
                "status": "PROCESSING",
                "currentUnitKey": getattr(checkpoint, "current_unit_key", None),
                "lastCompletedUnitKey": getattr(
                    checkpoint, "last_completed_unit_key", None
                ),
                "cursorBefore": getattr(checkpoint, "cursor_before", None),
                "cursorAfter": getattr(checkpoint, "cursor_after", None),
            },
        )
        await _persist_runtime_observation(
            db,
            run,
            runtime_state,
            status="UNIT_STARTED",
            result={"stage": IngestionStage.READING.value},
            unit=unit,
            checkpoint=checkpoint,
            message="Source unit claimed for ingestion.",
        )

    async def observe_unit(unit: SourceUnitMetadata, result: Any, checkpoint: Any) -> None:
        if isinstance(result, dict) and result.get("outcome") == "CLAIMED":
            await observe_unit_started(unit, checkpoint)
            return
        payload = _runtime_event_result(result, unit=unit, checkpoint=checkpoint)
        waiting_for_review = (
            payload.get("outcome") == "WAITING_REVIEW"
            or payload.get("waitingForReview") is True
        )
        if waiting_for_review:
            runtime_state.begin_stage(
                IngestionStage.CONFIGURING.value
                if payload.get("errorCode") == "configuration_approval_required"
                else IngestionStage.QUARANTINING.value
            )
        successful = not waiting_for_review and (
            bool(payload.get("success"))
            or payload.get("outcome")
            in {
                "INGESTED",
                "PARTIAL",
                "FILE_DUPLICATE",
                "FETCH_UNIT_REPLAY",
            }
        )
        checkpoint_after = _checkpoint_context(checkpoint)
        if successful:
            checkpoint_after.update(
                {
                    "status": "COMPLETED",
                    "currentUnitKey": unit.source_unit_key,
                    "lastCompletedUnitKey": unit.source_unit_key,
                    "cursorAfter": unit.cursor_after,
                }
            )
        elif waiting_for_review:
            checkpoint_after.update(
                {
                    "status": "DISCOVERED",
                    "currentUnitKey": None,
                }
            )
        else:
            checkpoint_after.update(
                {
                    "status": "FAILED",
                    "currentUnitKey": unit.source_unit_key,
                }
            )
        payload["checkpointAfter"] = checkpoint_after
        if payload.get("outcome") in {"FILE_DUPLICATE", "FETCH_UNIT_REPLAY"}:
            # A safe replay must not inherit counters from the already-finished
            # source file it references.
            payload.pop("stageSummary", None)
        await _persist_runtime_observation(
            db,
            run,
            runtime_state,
            status="UNIT_COMPLETED" if successful else "UNIT_FAILED",
            result=payload,
            unit=unit,
            checkpoint=checkpoint,
            message=("Source unit ingestion completed." if successful else payload.get("error")),
        )

    context = StreamRunContext(
        config=config,
        db=db,
        config_loader=config_loader,
        reconciliation_date=reconciliation_date,
        batch_size=batch_size,
        structured_logger=structured_logger,
        mode=mode,
        runtime_run_id=str(run.id),
        mapping_config_version=mapping_config_version,
        backfill_run_id=backfill_run_id,
        identity=identity,
        checkpoint_repo=checkpoint_repo,
        checkpoint=checkpoint,
        fetcher=fetcher,
        ingest_unit=ingest_unit,
        stats=stats,
        retry_policy=retry_policy,
        raw_page_repo=raw_page_repo,
        stage_key=stage_key,
        run=run,
        cleanup_unit=cleanup_unit,
        on_unit_observed=observe_unit,
        dependencies=StreamRunnerDependencies(
            process_source_units=process_source_units,
            stage_stream_unit=stage_stream_unit,
            evaluate_stream_mapping=evaluate_stream_mapping,
            create_stream_review_packet=create_stream_review_packet,
            mapping_config_repository=MappingConfigRepository,
            ingestion_error_result=ingestion_error_result,
        ),
    )

    try:
        method_config = config.get_method_config()
        selected_runner = select_stream_runner(config)
        result = await selected_runner(context=context, method_config=method_config)
        return await lifecycle.finish(result, stats)
    except Exception as exc:
        failed_result = await lifecycle.finish(
            unexpected_failure_result(exc, summarize_error=summarize_runtime_error),
            stats,
        )
        if raise_on_unexpected:
            raise
        return failed_result


__all__ = ["run_source_stream"]
