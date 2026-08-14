"""Application runner for one configured source stream."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.application.automation.stream_identity import (
    raw_stage_key as build_raw_stage_key,
    stream_identity,
    units_after_checkpoint,
)
from src.application.automation.stream_fetching import (
    checkpoint_result,
    source_units,
    unit_high_water_mark,
)
from src.application.automation.stream_staging import stage_stream_unit
from src.application.automation.stream_review_gate import (
    create_stream_review_packet,
    evaluate_stream_mapping,
)
from src.application.automation.stream_ingestion import (
    build_source_unit_ingestor,
    cleanup_source_unit,
    ingestion_error_result,
)
from src.application.automation.stream_runtime import (
    finish_source_stream_run,
    runtime_attempt_event,
)
from src.application.ingestion.source_unit_orchestrator import process_source_units
from src.config.config_health import (
    ConfigurationApprovalRequiredError,
)
from src.core.enums import FileType
from src.core.error_formatting import summarize_runtime_error
from src.domain.fetch_config.models import FetchConfig, FetchMethod
from src.domain.ingestion.checkpoints import CheckpointStatus, IngestionMode
from src.domain.ingestion.source_units import SourceUnitMetadata
from src.domain.runtime.models import (
    PartnerRuntimeRunStatus,
    PartnerRuntimeTriggerType,
    RuntimeOrchestrationContext,
)
from src.fetchers import create_fetcher
from src.infrastructure.ingestion.checkpoint_repository import IngestionCheckpointRepository
from src.infrastructure.ingestion.raw_page_repository import RawIngestionPageRepository
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.infrastructure.runtime.repository import PartnerRuntimeRunRepository
from src.logging import StructuredLogger
from src.application.runtime.service import create_runtime_run, update_runtime_run
from src.domain.ingestion.retry_policy import RetryPolicy

logger = logging.getLogger("reconciliation.automation.stream_runner")


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

    if runtime_run_id is None:
        run = await create_runtime_run(
            db,
            partner=config.partner,
            date=reconciliation_date.strftime("%Y-%m-%d"),
            trigger_type=PartnerRuntimeTriggerType.SCHEDULER,
            triggered_by="system:scheduler",
            status=PartnerRuntimeRunStatus.FETCHING,
            message="Fetching source units sequentially.",
            orchestration=orchestration,
        )
    else:
        existing_run = await PartnerRuntimeRunRepository(db).find_one({"_id": runtime_run_id})
        if existing_run is None:
            raise ValueError(f"Runtime run '{runtime_run_id}' was not found.")
        run = existing_run
        if orchestration is not None:
            # Build the STARTED event from the current Airflow try number.
            # The persisted runtime still contains the previous try until the
            # update below, which otherwise labels a manual retry as attempt 1.
            run.orchestration = RuntimeOrchestrationContext.model_validate(orchestration)
        await update_runtime_run(
            db,
            str(run.id),
            status=PartnerRuntimeRunStatus.FETCHING,
            message="Fetching source units sequentially.",
            orchestration=orchestration,
            attempt_event=runtime_attempt_event(
                run,
                "STARTED",
                message="Fetching source units sequentially.",
            ),
        )
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
    if checkpoint and checkpoint.status == CheckpointStatus.BLOCKED:
        return await finish_source_stream_run(
            db=db,
            run=run,
            partner=config.partner,
            result={
                "success": False,
                "outcome": "BLOCKED",
                "processed": 0,
                "failed": 1,
                "stoppedAt": checkpoint.current_unit_key,
                "error": "Source stream is BLOCKED and requires operator resolution.",
                "errorCode": checkpoint.error_code or "checkpoint_blocked",
                "retryable": False,
                "checkpoint": checkpoint_result(checkpoint),
            },
            stats={"totalRows": 0, "successRows": 0, "duplicateRows": 0, "failedRows": 0, "unitsProcessed": 0},
        )
    if checkpoint and checkpoint.stream_ended:
        return await finish_source_stream_run(
            db=db,
            run=run,
            partner=config.partner,
            result={
                "success": True,
                "processed": 0,
                "failed": 0,
                "reconciliationSkipped": True,
                "streamAlreadyCompleted": True,
                "checkpoint": checkpoint_result(checkpoint),
            },
            stats={"totalRows": 0, "successRows": 0, "duplicateRows": 0, "failedRows": 0, "unitsProcessed": 0},
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
    stage_key = (
        build_raw_stage_key(config, reconciliation_date)
        if config.fetch_method == FetchMethod.API
        else None
    )
    await update_runtime_run(
        db,
        str(run.id),
        status=PartnerRuntimeRunStatus.INGESTING,
        message="Processing source units sequentially.",
    )

    try:
        method_config = config.get_method_config()
        if config.fetch_method == FetchMethod.API and method_config.pagination:
            if stage_key is None:
                raise RuntimeError("API source streams require a raw staging key.")
            fetch_metadata: dict[str, Any] = {
                "singleUnit": True,
                "configVersion": identity["configVersion"],
            }
            previous_unit_key = checkpoint.last_completed_unit_key if checkpoint else None
            if checkpoint:
                stored_page = (checkpoint.stream_metadata or {}).get("page")
                if checkpoint.status in {CheckpointStatus.FAILED, CheckpointStatus.PROCESSING} and stored_page:
                    fetch_metadata["page"] = stored_page
                    fetch_metadata["cursor"] = checkpoint.cursor_before
                elif checkpoint.high_water_mark and checkpoint.high_water_mark.get("page"):
                    fetch_metadata["page"] = checkpoint.high_water_mark["page"] + 1
                    fetch_metadata["cursor"] = checkpoint.cursor_after

            staged_units: list[SourceUnitMetadata] = []
            raw_staging_available = True
            while True:
                fetch_result = await fetcher.fetch(
                    method_config,
                    reconciliation_date,
                    fetch_metadata=fetch_metadata,
                )
                if not fetch_result.success:
                    if fetch_result.units:
                        failed_unit = SourceUnitMetadata.from_payload(fetch_result.units[-1])
                        logger.warning(
                            "source_unit_fetch_failed partner=%s runtimeRunId=%s "
                            "streamKey=%s sourceUnitKey=%s page=%s cursorBefore=%s "
                            "statusCode=%s errorCode=%s error=%s",
                            identity["partner"],
                            runtime_run_id or "-",
                            identity["streamKey"],
                            failed_unit.source_unit_key or "-",
                            failed_unit.page or "-",
                            failed_unit.cursor_before or "-",
                            failed_unit.status_code or "-",
                            failed_unit.error_code or "-",
                            fetch_result.error or failed_unit.error or "-",
                        )

                        async def fetch_failure(_: SourceUnitMetadata) -> dict[str, Any]:
                            error_code = failed_unit.error_code or (
                                "fetch_http_4xx"
                                if "status 4" in (fetch_result.error or "")
                                else "fetch_http_5xx"
                                if "status 5" in (fetch_result.error or "")
                                else "fetch_network_error"
                            )
                            return ingestion_error_result(
                                fetch_result.error or "API source unit fetch failed",
                                error_code,
                                retryable=retry_policy.classify(error_code).value == "RETRYABLE",
                            )

                        # In the durable-staging path successful pages are not
                        # claimed/completed until the complete stream has been
                        # fetched.  Do not claim page N with page N-1 as the
                        # checkpoint predecessor: that predecessor only exists
                        # in the local fetch cursor, not in Mongo yet.  Doing so
                        # produced the misleading "claim was not acquired"
                        # error after an Airflow page-fetch failure.
                        can_resume_failed_unit = (
                            checkpoint is not None
                            and checkpoint.last_completed_unit_key == previous_unit_key
                        )
                        if can_resume_failed_unit:
                            failed_result = await process_source_units(
                                checkpoint_repo,
                                stream_identity={
                                    **identity,
                                    "lastCompletedUnitKey": previous_unit_key,
                                    "streamMetadata": {"page": failed_unit.page},
                                },
                                units=[failed_unit],
                                ingest_unit=fetch_failure,
                                mode=mode,
                                retry_policy=retry_policy,
                                on_unit_completed=cleanup_unit,
                            )
                        else:
                            failed_result = {
                                "success": False,
                                "processed": 0,
                                "failed": 1,
                                "fetchedUnitCount": len(staged_units),
                                "totalUnitCount": getattr(method_config.pagination, "max_pages", len(staged_units)),
                                "currentPage": failed_unit.page,
                                "stoppedAt": failed_unit.source_unit_key,
                                "error": fetch_result.error or failed_unit.error or "API source unit fetch failed",
                                "errorCode": failed_unit.error_code or "fetch_network_error",
                                "retryable": retry_policy.classify(
                                    failed_unit.error_code or "fetch_network_error"
                                ).value == "RETRYABLE",
                            }
                        return await finish_source_stream_run(
                            db=db, run=run, partner=config.partner, result=failed_result, stats=stats
                        )
                    fetch_error = fetch_result.error or "API source unit fetch failed"
                    fetch_error_code = fetch_result.metadata.get("errorCode") or (
                        "fetch_http_4xx"
                        if "status 4" in fetch_error
                        else "fetch_http_5xx"
                        if "status 5" in fetch_error
                        else "fetch_network_error"
                    )
                    logger.error(
                        "source_stream_fetch_failed partner=%s runtimeRunId=%s "
                        "streamKey=%s errorCode=%s error=%s",
                        identity["partner"],
                        runtime_run_id or "-",
                        identity["streamKey"],
                        fetch_error_code,
                        fetch_error,
                    )
                    return await finish_source_stream_run(
                        db=db,
                        run=run,
                        partner=config.partner,
                        result={
                            "success": False,
                            "processed": 0,
                            "failed": 1,
                            "fetchedUnitCount": 0,
                            "totalUnitCount": getattr(method_config.pagination, "max_pages", 0),
                            "error": fetch_error,
                            "errorCode": fetch_error_code,
                            "retryable": retry_policy.classify(fetch_error_code).value == "RETRYABLE",
                        },
                        stats=stats,
                    )

                unit = SourceUnitMetadata.from_payload(fetch_result.units[0])
                logger.info(
                    "source_unit_fetched partner=%s runtimeRunId=%s streamKey=%s "
                    "sourceUnitKey=%s page=%s cursorBefore=%s cursorAfter=%s "
                    "itemCount=%s hasMore=%s",
                    identity["partner"],
                    runtime_run_id or "-",
                    identity["streamKey"],
                    unit.source_unit_key or "-",
                    unit.page or "-",
                    unit.cursor_before or "-",
                    unit.cursor_after or "-",
                    unit.item_count,
                    fetch_result.metadata["pagination"].get("has_more"),
                )
                unit.has_more = fetch_result.metadata["pagination"].get("has_more")
                unit.high_water_mark = unit_high_water_mark(unit)
                unit.fetch_metadata = {
                    **unit.fetch_metadata,
                    "rawStageKey": stage_key,
                }
                if raw_staging_available:
                    raw_staging_available = await stage_stream_unit(
                        raw_page_repo,
                        stage_key=stage_key,
                        partner=identity["partner"],
                        fetch_config_id=identity["fetchConfigId"],
                        source_type=identity["sourceType"],
                        stream_key=identity["streamKey"],
                        reconciliation_date=reconciliation_date,
                        unit=unit,
                    )
                staged_units.append(unit)
                if not raw_staging_available:
                    # Preserve the legacy one-page-at-a-time path for adapters
                    # that do not support durable staging (notably lightweight
                    # test doubles). Real Motor databases continue fetching
                    # and staging the whole stream before the mapping gate.
                    unit_result = await process_source_units(
                        checkpoint_repo,
                        stream_identity={
                            **identity,
                            "lastCompletedUnitKey": previous_unit_key,
                            "streamMetadata": {"page": unit.page},
                        },
                        units=[unit],
                        ingest_unit=ingest_unit,
                        mode=mode,
                        retry_policy=retry_policy,
                        on_unit_completed=cleanup_unit,
                    )
                    if (
                        not unit_result["success"]
                        or unit_result.get("outcome") == "WAITING_REVIEW"
                        or unit_result.get("waitingForReview") is True
                    ):
                        return await finish_source_stream_run(
                            db=db, run=run, partner=config.partner, result=unit_result, stats=stats
                        )
                    if not fetch_result.metadata["pagination"].get("has_more"):
                        return await finish_source_stream_run(
                            db=db, run=run, partner=config.partner, result=unit_result, stats=stats
                        )
                    previous_unit_key = unit.source_unit_key
                    fetch_metadata = {
                        "singleUnit": True,
                        "page": (unit.page or 0) + 1,
                        "cursor": unit.cursor_after,
                        "configVersion": identity["configVersion"],
                    }
                    continue
                if not fetch_result.metadata["pagination"].get("has_more"):
                    break
                previous_unit_key = unit.source_unit_key
                fetch_metadata = {
                    "singleUnit": True,
                    "page": (unit.page or 0) + 1,
                    "cursor": unit.cursor_after,
                    "configVersion": identity["configVersion"],
                }

            async def mark_page_consumed(unit: SourceUnitMetadata) -> None:
                if raw_staging_available:
                    await raw_page_repo.mark_consumed(unit.source_unit_key or "")
                await cleanup_unit(unit)

            # The review gate is evaluated only after the complete API stream
            # has been fetched and staged. This prevents a page-1 success from
            # creating a packet while page 2/3 is still unknown or failing.
            first_staged_unit = staged_units[0] if staged_units else None
            if first_staged_unit is not None:
                active_runtime_config = None
                try:
                    active_runtime_config = await evaluate_stream_mapping(
                        file_path=first_staged_unit.local_path or "",
                        partner=config.partner,
                        workflow_type="UPC",
                        file_type=FileType.SETTLEMENT,
                        config_loader=config_loader,
                        config_repo=MappingConfigRepository(db),
                        source_file_name=Path(first_staged_unit.local_path or "").name,
                        source_file_path=first_staged_unit.local_path,
                        reconciliation_date=reconciliation_date,
                        raw_stage_key=stage_key,
                        backfill_run_id=backfill_run_id,
                    )
                except ConfigurationApprovalRequiredError as approval_exc:
                    review_checkpoint, won_review_claim = await checkpoint_repo.claim_unit(
                        partner=identity["partner"],
                        fetch_config_id=identity["fetchConfigId"],
                        source_type=identity["sourceType"],
                        stream_key=identity["streamKey"],
                        unit_key=first_staged_unit.source_unit_key or "",
                        mode=mode,
                        cursor_before=first_staged_unit.cursor_before,
                        expected_previous_unit_key=(
                            checkpoint.last_completed_unit_key if checkpoint else None
                        ),
                        config_version=identity["configVersion"],
                        source_endpoint=identity["sourceEndpoint"],
                        stream_metadata={"page": first_staged_unit.page},
                    )
                    if won_review_claim:
                        await checkpoint_repo.release_for_review(
                            review_checkpoint,
                            unit_key=first_staged_unit.source_unit_key or "",
                            reason=str(approval_exc),
                        )
                    review_result = {
                        "success": True,
                        "processed": 0,
                        "failed": 0,
                        "fetchedUnitCount": len(staged_units),
                        "totalUnitCount": len(staged_units),
                        "stoppedAt": first_staged_unit.source_unit_key,
                        "outcome": "WAITING_REVIEW",
                        "waitingForReview": True,
                        "error": str(approval_exc),
                        "errorCode": "configuration_approval_required",
                        "rawStageKey": stage_key,
                    }
                    return await finish_source_stream_run(
                        db=db,
                        run=run,
                        partner=config.partner,
                        result=review_result,
                        stats=stats,
                    )
                except Exception as exc:
                    logger.warning(
                        "Preflight mapping check failed for staged stream %s: %s",
                        stage_key,
                        exc,
                    )

                if active_runtime_config is not None:
                    await create_stream_review_packet(
                        database=db,
                        partner=config.partner,
                        file_type=FileType.SETTLEMENT,
                        active_runtime_config=active_runtime_config,
                        source_file_name=Path(first_staged_unit.local_path or "").name,
                        source_file_path=first_staged_unit.local_path,
                        reconciliation_date=reconciliation_date,
                        raw_stage_key=stage_key,
                        backfill_run_id=backfill_run_id,
                    )
                    review_checkpoint, won_review_claim = await checkpoint_repo.claim_unit(
                        partner=identity["partner"],
                        fetch_config_id=identity["fetchConfigId"],
                        source_type=identity["sourceType"],
                        stream_key=identity["streamKey"],
                        unit_key=first_staged_unit.source_unit_key or "",
                        mode=mode,
                        cursor_before=first_staged_unit.cursor_before,
                        expected_previous_unit_key=checkpoint.last_completed_unit_key if checkpoint else None,
                        config_version=identity["configVersion"],
                        source_endpoint=identity["sourceEndpoint"],
                        stream_metadata={"page": first_staged_unit.page},
                    )
                    if won_review_claim:
                        await checkpoint_repo.release_for_review(
                            review_checkpoint,
                            unit_key=first_staged_unit.source_unit_key or "",
                            reason="Complete paginated API stream awaits scope review.",
                        )
                    return await finish_source_stream_run(
                        db=db,
                        run=run,
                        partner=config.partner,
                        result={
                            "success": True, "processed": 0, "failed": 0,
                            "fetchedUnitCount": len(staged_units), "totalUnitCount": len(staged_units),
                            "stoppedAt": first_staged_unit.source_unit_key,
                            "outcome": "WAITING_REVIEW", "waitingForReview": True,
                            "rawStageKey": stage_key,
                        },
                        stats=stats,
                    )

            result = await process_source_units(
                checkpoint_repo,
                stream_identity={
                    **identity,
                    "lastCompletedUnitKey": checkpoint.last_completed_unit_key
                    if checkpoint
                    else None,
                },
                units=staged_units,
                ingest_unit=ingest_unit,
                mode=mode,
                retry_policy=retry_policy,
                on_unit_completed=mark_page_consumed,
            )
            result["fetchedUnitCount"] = len(staged_units)
            result["totalUnitCount"] = len(staged_units)
            return await finish_source_stream_run(
                db=db, run=run, partner=config.partner, result=result, stats=stats
            )

        fetch_result = await fetcher.fetch(
            method_config,
            reconciliation_date,
            fetch_metadata={"configVersion": identity["configVersion"]},
        )
        if not fetch_result.success:
            no_new_file = (
                fetch_result.metadata.get("scanned_files") == 0
                and "No files matching" in (fetch_result.error or "")
            )
            if no_new_file:
                return await finish_source_stream_run(
                    db=db,
                    run=run,
                    partner=config.partner,
                    result={"success": True, "processed": 0, "failed": 0, "outcome": "NO_NEW_FILE"},
                    stats=stats,
                )
            return await finish_source_stream_run(
                db=db,
                run=run,
                partner=config.partner,
                result={"success": False, "processed": 0, "failed": 1, "error": fetch_result.error},
                stats=stats,
            )

        fetched_units = source_units(fetch_result.units or [])
        units = units_after_checkpoint(fetched_units, checkpoint)
        if fetched_units and not units:
            return await finish_source_stream_run(
                db=db,
                run=run,
                partner=config.partner,
                result={
                    "success": True,
                    "processed": 0,
                    "failed": 0,
                    "replayed": len(fetched_units),
                    "outcome": "FETCH_UNIT_REPLAY",
                    "reconciliationSkipped": True,
                },
                stats=stats,
            )
        if not fetched_units:
            return await finish_source_stream_run(
                db=db,
                run=run,
                partner=config.partner,
                result={
                    "success": True,
                    "processed": 0,
                    "failed": 0,
                    "outcome": "NO_NEW_FILE",
                    "reconciliationSkipped": True,
                },
                stats=stats,
            )
        for unit in units:
            unit.fetch_metadata = {
                **fetch_result.metadata,
                **({"rawStageKey": stage_key} if stage_key else {}),
            }
            unit.high_water_mark = unit_high_water_mark(unit)
        result = await process_source_units(
            checkpoint_repo,
            stream_identity={
                **identity,
                "lastCompletedUnitKey": checkpoint.last_completed_unit_key
                if checkpoint
                else None,
            },
            units=units,
            ingest_unit=ingest_unit,
            mode=mode,
            retry_policy=retry_policy,
            on_unit_completed=cleanup_unit,
        )
        return await finish_source_stream_run(
            db=db, run=run, partner=config.partner, result=result, stats=stats
        )
    except Exception as exc:
        summarized_error = summarize_runtime_error(exc)
        failed_result = await finish_source_stream_run(
            db=db,
            run=run,
            partner=config.partner,
            result={"success": False, "processed": 0, "failed": 1, "error": summarized_error},
            stats=stats,
        )
        if raise_on_unexpected:
            raise
        return failed_result




__all__ = ["run_source_stream"]
