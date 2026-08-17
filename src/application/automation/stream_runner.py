"""Public dispatcher for one configured source stream."""

import logging
from datetime import datetime
from typing import Any, Optional

from src.application.automation.file_stream_runner import run_file_stream
from src.application.automation.paginated_stream_runner import run_paginated_stream
from src.application.automation.stream_failure import unexpected_failure_result
from src.application.automation.stream_fetching import checkpoint_result
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
from src.application.automation.stream_review_gate import (
    create_stream_review_packet,
    evaluate_stream_mapping,
)
from src.application.automation.stream_runtime import (
    finish_source_stream_run,
    runtime_attempt_event,
)
from src.application.automation.stream_staging import stage_stream_unit
from src.application.ingestion.source_unit_orchestrator import process_source_units
from src.application.runtime.service import create_runtime_run, update_runtime_run
from src.core.error_formatting import summarize_runtime_error
from src.domain.fetch_config.models import FetchConfig, FetchMethod
from src.domain.ingestion.checkpoints import IngestionMode
from src.domain.ingestion.retry_policy import RetryPolicy
from src.domain.ingestion.source_units import SourceUnitMetadata
from src.fetchers import create_fetcher
from src.infrastructure.ingestion.checkpoint_repository import IngestionCheckpointRepository
from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository
from src.infrastructure.ingestion.raw_page_repository import RawIngestionPageRepository
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.infrastructure.runtime.repository import PartnerRuntimeRunRepository
from src.logging import StructuredLogger

logger = logging.getLogger("reconciliation.automation.stream_runner")


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
    identity = stream_identity(
        config,
        mode=mode,
        reconciliation_date=reconciliation_date,
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
        # A backfill compares the pinned config with each day's source
        # structure. Equivalent days return the same approved config; a drift
        # day raises a review outcome and releases its checkpoint.
        config_health_check_enabled=True,
    )
    retry_policy = RetryPolicy()
    raw_page_repo = RawIngestionPageRepository(db)
    await lifecycle.mark_ingesting()

    context = StreamRunContext(
        config=config,
        db=db,
        config_loader=config_loader,
        reconciliation_date=reconciliation_date,
        batch_size=batch_size,
        structured_logger=structured_logger,
        mode=mode,
        runtime_run_id=runtime_run_id,
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
