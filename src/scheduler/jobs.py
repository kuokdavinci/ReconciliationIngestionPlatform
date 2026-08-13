"""Daily fetch job definitions.

Defines the job that runs at scheduled times to fetch data from all enabled
partners and trigger the ingestion pipeline.
"""

import logging
from datetime import datetime, timezone
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from src.config.loader import ConfigLoader
from src.config.settings import settings
from src.config.config_health import (
    ConfigurationApprovalRequiredError,
    check_and_refresh_config,
    create_stream_scope_review_packet,
)
from src.core.enums import FileType, ProcessingStatus
from src.core.error_formatting import summarize_runtime_error
from src.fetchers import create_fetcher
from src.fetchers.base import BaseFetcher
from src.logging import StructuredLogger
from src.domain.fetch_config.models import FetchConfig, FetchMethod
from src.infrastructure.fetch_config.repository import FetchConfigRepository
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.domain.ingestion.checkpoints import CheckpointStatus, IngestionMode
from src.infrastructure.ingestion.checkpoint_repository import IngestionCheckpointRepository
from src.infrastructure.ingestion.raw_page_repository import RawIngestionPageRepository
from src.infrastructure.runtime.repository import PartnerRuntimeRunRepository
from src.domain.ingestion.source_units import SourceUnitMetadata
from src.application.reconciliation.service import ReconciliationCommand
from src.infrastructure.reconciliation.composition import build_reconciliation_service
from src.infrastructure.ingestion.composition import build_ingestion_pipeline
from src.services.runtime_runs import create_runtime_run, update_runtime_run
from src.services.retry_policy import RetryPolicy
from src.application.ingestion.source_unit_orchestrator import process_source_units
from src.application.ingestion.error_classification import is_missing_ingestion_key_failure
from src.domain.runtime.models import (
    PartnerRuntimeRunStatus,
    PartnerRuntimeTriggerType,
    RuntimeOrchestrationContext,
)

logger = logging.getLogger("reconciliation.jobs")


def _runtime_attempt_event(
    run: Any,
    status: str,
    *,
    result: dict[str, Any] | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    """Build a compact, safe event for one application runtime attempt."""

    orchestration = getattr(run, "orchestration", None)
    event: dict[str, Any] = {
        "eventId": str(uuid4()),
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attempt": getattr(orchestration, "try_number", 1),
    }
    if orchestration is not None:
        event.update(
            {
                "dagRunId": orchestration.dag_run_id,
                "taskId": orchestration.task_id,
                "mapIndex": orchestration.map_index,
            }
        )
    if result:
        event.update(
            {
                key: result[key]
                for key in (
                    "outcome",
                    "errorCode",
                    "currentPage",
                    "stoppedAt",
                    "fetchedUnitCount",
                    "totalUnitCount",
                )
                if result.get(key) is not None
            }
        )
        if result.get("stoppedAt") is not None:
            event["unitKey"] = result["stoppedAt"]
    if message:
        event["message"] = message
    return event


def _fetch_source_endpoint(config: FetchConfig) -> str:
    method_config = config.get_method_config()
    if config.fetch_method == FetchMethod.API:
        return method_config.base_url
    if config.fetch_method == FetchMethod.SFTP:
        return f"sftp://{method_config.host}:{method_config.port}{method_config.remote_path}"
    if config.fetch_method == FetchMethod.FILEDROP:
        return f"filedrop://{method_config.directory}/{method_config.pattern}"
    raise ValueError(f"Unsupported fetch method: {config.fetch_method}")


def _fetch_unit_metadata(
    config: FetchConfig,
    fetch_metadata: dict[str, Any],
    reconciliation_date: datetime,
) -> dict[str, Any]:
    metadata = {
        **fetch_metadata,
        "sourceEndpoint": _fetch_source_endpoint(config),
        "windowStart": reconciliation_date.isoformat(),
        "windowEnd": reconciliation_date.isoformat(),
    }
    if config.fetch_method == FetchMethod.FILEDROP:
        metadata["cursor"] = fetch_metadata.get("selected_file")
    return metadata


def _source_stream_key(config: FetchConfig) -> str:
    """Return a stable logical stream identity, independent of run date."""

    return f"{config.partner}:{config.fetch_method.value}:{_fetch_source_endpoint(config)}"


def _raw_stage_key(config: FetchConfig, reconciliation_date: datetime) -> str:
    """Stable raw-page staging identity for one partner/date/config version."""

    return ":".join(
        (
            config.partner,
            _source_stream_key(config),
            reconciliation_date.date().isoformat(),
            str(config.updated_at),
        )
    )


def _current_business_day_start(now: datetime | None = None) -> datetime:
    """Return today's configured business date at local midnight."""

    business_timezone = ZoneInfo(settings.business_timezone)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(business_timezone).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def _stream_identity(
    config: FetchConfig,
    *,
    mode: IngestionMode = IngestionMode.SCHEDULED,
    reconciliation_date: datetime | None = None,
) -> dict[str, Any]:
    stream_key = _source_stream_key(config)
    if mode == IngestionMode.BACKFILL:
        if reconciliation_date is None:
            raise ValueError("Backfill stream identity requires reconciliation_date.")
        stream_key = f"{stream_key}:backfill:{reconciliation_date.date().isoformat()}"
    return {
        "partner": config.partner,
        "fetchConfigId": str(config.id),
        "sourceType": config.fetch_method.value,
        "streamKey": stream_key,
        "configVersion": str(config.updated_at),
        "sourceEndpoint": _fetch_source_endpoint(config),
    }


def _checkpoint_result(checkpoint: Any) -> dict[str, Any]:
    status = getattr(checkpoint.status, "value", checkpoint.status)
    return {
        "status": status,
        "currentUnitKey": checkpoint.current_unit_key,
        "lastCompletedUnitKey": checkpoint.last_completed_unit_key,
        "cursorBefore": checkpoint.cursor_before,
        "cursorAfter": checkpoint.cursor_after,
    }


def _source_units(
    units: Sequence[SourceUnitMetadata | dict[str, Any]],
) -> list[SourceUnitMetadata]:
    return [SourceUnitMetadata.from_payload(unit) for unit in units]


def _unit_high_water_mark(unit: SourceUnitMetadata) -> dict[str, Any]:
    return {
        "sourceUnitKey": unit.source_unit_key,
        "page": unit.page,
        "cursorAfter": unit.cursor_after,
        "contentHash": unit.content_hash,
        "hasMore": unit.has_more,
    }


def _units_after_checkpoint(
    units: Sequence[SourceUnitMetadata | dict[str, Any]], checkpoint: Any
) -> list[SourceUnitMetadata]:
    """Skip the already completed prefix discovered in the same order."""

    units = _source_units(units)
    completed_key = getattr(checkpoint, "last_completed_unit_key", None)
    completed_hash = (getattr(checkpoint, "high_water_mark", None) or {}).get("contentHash")
    if not completed_key:
        completed_key = None
    for index, unit in enumerate(units):
        # The content-hash fallback keeps checkpoints created before the
        # mtime-independent source-unit identity change replay-safe.
        if unit.source_unit_key == completed_key or (
            completed_hash and unit.content_hash == completed_hash
        ):
            return units[index + 1 :]
    return units


def _ingestion_error_result(
    message: str,
    error_code: str,
    *,
    retryable: bool | None = None,
) -> dict[str, Any]:
    return {
        "success": False,
        "error": message,
        "errorCode": error_code,
        "retryable": (
            error_code in {"source_persist_error", "checkpoint_advance_error"}
            if retryable is None
            else retryable
        ),
    }


def _failed_ingestion_result(result: Any) -> dict[str, Any]:
    """Translate a failed file result into a precise source-unit error."""
    stats = getattr(result, "stats", None)
    errors = getattr(result, "errors", None) or []
    if stats is not None and is_missing_ingestion_key_failure(
        total_rows=getattr(stats, "total_rows", 0),
        success_rows=getattr(stats, "success_rows", 0),
        failed_rows=getattr(stats, "failed_rows", 0),
        errors=errors,
    ):
        return _ingestion_error_result(
            "Unable to derive ingestion_key: both id and trace are missing from the source rows.",
            "ingestion_key_error",
            retryable=False,
        )

    file_record = getattr(result, "file_record", None)
    stage_summary = getattr(file_record, "stage_summary", None) or {}
    is_read_failure = stage_summary.get("currentStage") == "READING"
    error_code = "file_parse_error" if is_read_failure else "source_persist_error"
    error = next(
        (
            str(item["reason"])
            for item in reversed(errors)
            if isinstance(item, dict) and item.get("reason")
        ),
        "Ingestion failed.",
    )
    return _ingestion_error_result(
        error,
        error_code,
        retryable=False if is_read_failure else None,
    )


async def _cleanup_source_unit(config: FetchConfig, unit: SourceUnitMetadata) -> None:
    """Release local source storage only after its checkpoint is committed."""

    if not config.cleanup_after_ingest or not unit.local_path:
        return
    if config.archive_dir:
        BaseFetcher.archive_file(
            unit.local_path,
            config.archive_dir,
            config.archive_retention_days,
        )
        return
    BaseFetcher.cleanup_file(unit.local_path)


def _build_source_unit_ingestor(
    *,
    config: FetchConfig,
    db: Any,
    config_loader: ConfigLoader,
    partner: str,
    reconciliation_date: datetime,
    batch_size: int,
    structured_logger: Optional[StructuredLogger],
    reconciliation_run_id: str | None = None,
    mapping_config_version: str | None = None,
) -> tuple[Any, dict[str, int]]:
    stats = {
        "totalRows": 0,
        "successRows": 0,
        "duplicateRows": 0,
        "failedRows": 0,
        "unitsProcessed": 0,
        "reconciliationCount": 0,
    }
    is_paginated_api = (
        config.fetch_method == FetchMethod.API
        and config.get_method_config().pagination is not None
    )
    config_health_checked = False

    async def ingest_unit(unit: SourceUnitMetadata | dict[str, Any]) -> dict[str, Any]:
        nonlocal config_health_checked
        unit = SourceUnitMetadata.from_payload(unit)
        file_path = unit.local_path
        if not file_path:
            return _ingestion_error_result(
                "Source unit is missing localPath", "source_persist_error"
            )

        unit_payload = unit.model_dump(by_alias=True)
        # ``fetchMetadata`` is a nested field in the Pydantic model. Merge the
        # fetcher's bounded page sample after the model dump so it is not
        # overwritten by the model's default empty mapping.
        unit_payload.update(unit.fetch_metadata)
        unit_metadata = _fetch_unit_metadata(
            config,
            unit_payload,
            reconciliation_date,
        )
        result = await _run_ingestion(
            db=db,
            config_loader=config_loader,
            file_path=file_path,
            partner=partner,
            reconciliation_date=reconciliation_date,
            batch_size=batch_size,
            structured_logger=structured_logger,
            fetch_unit_metadata=unit_metadata,
            config_version=mapping_config_version,
            enable_config_health_check=(not config_health_checked or not is_paginated_api),
            validate_rows=config.validate_rows,
        )
        if not result or not result.file_record:
            return _ingestion_error_result(
                "Ingestion pipeline did not return a file record.",
                "source_persist_error",
            )

        stats["unitsProcessed"] += 1
        stats["totalRows"] += result.stats.total_rows
        stats["successRows"] += result.stats.success_rows
        stats["duplicateRows"] += result.stats.duplicate_rows
        stats["failedRows"] += result.stats.failed_rows

        outcome = getattr(result, "outcome", "INGESTED")
        if outcome in {"FILE_DUPLICATE", "FETCH_UNIT_REPLAY"}:
            return {
                "success": True,
                "outcome": outcome,
                "duplicateCode": getattr(result, "duplicate_code", None),
            }

        if is_paginated_api:
            config_health_checked = True

        processing_status = getattr(
            result.file_record.processing_status,
            "value",
            result.file_record.processing_status,
        )
        waiting_for_review = (
            outcome == "WAITING_REVIEW"
            or processing_status == ProcessingStatus.PENDING.value
            or any(
                "configuration approval required" in str(err.get("reason", "")).lower()
                for err in (result.errors or [])
            )
        )
        if processing_status != ProcessingStatus.COMPLETED.value:
            if waiting_for_review:
                return {
                    "success": False,
                    "outcome": "WAITING_REVIEW",
                    "waitingForReview": True,
                    "error": "Ingestion is waiting for configuration approval. Operator action is required.",
                    "errorCode": "configuration_approval_required",
                    "retryable": False,
                }
            return _failed_ingestion_result(result)

        reconciliation_results = await build_reconciliation_service(db, fast_mode=True).execute(
            ReconciliationCommand(
                partner=partner,
                reconciliation_date=reconciliation_date,
                source_file_id=str(result.file_record.id),
                reconciliation_run_id=reconciliation_run_id,
            )
        )
        stats["reconciliationCount"] += len(reconciliation_results)
        return {
            "success": True,
            "outcome": "INGESTED",
            "reconciliationCount": len(reconciliation_results),
        }

    return ingest_unit, stats


async def _finish_source_stream_run(
    *,
    db: Any,
    run: Any,
    partner: str,
    result: dict[str, Any],
    stats: dict[str, int],
) -> dict[str, Any]:
    duplicate_messages = {
        "FILE_DUPLICATE": "File already processed. Ingestion and reconciliation were skipped safely.",
        "FETCH_UNIT_REPLAY": "Fetch unit already processed. Ingestion and reconciliation were skipped safely.",
        "NO_NEW_FILE": "No new file was found. Ingestion and reconciliation were skipped.",
        "SAFE_DUPLICATE": "This source file was already processed. The retry was skipped safely.",
    }
    waiting_for_review = (
        result.get("outcome") == "WAITING_REVIEW"
        or result.get("waitingForReview") is True
    )
    duplicate_source_outcome = result.get("outcome")
    if result.get("streamAlreadyCompleted"):
        duplicate_source_outcome = "STREAM_ALREADY_COMPLETED"
        result = {
            **result,
            "outcome": "SAFE_DUPLICATE",
            "safeDuplicate": True,
            "duplicateSourceOutcome": duplicate_source_outcome,
        }
    elif duplicate_source_outcome in duplicate_messages:
        result = {
            **result,
            "safeDuplicate": True,
            "duplicateSourceOutcome": duplicate_source_outcome,
        }
    persisted_stats = {**stats, **result}
    if waiting_for_review:
        terminal_status = PartnerRuntimeRunStatus.WAITING_REVIEW
        await update_runtime_run(
            db,
            str(run.id),
            status=terminal_status,
            message=result.get("error")
            or "A draft mapping is waiting for review before ingestion can continue.",
            stats=persisted_stats,
            finished_at=datetime.now(timezone.utc),
            attempt_event=_runtime_attempt_event(
                run,
                terminal_status.value,
                result=result,
                message=result.get("error"),
            ),
        )
    elif result.get("success"):
        terminal_status = PartnerRuntimeRunStatus.COMPLETED
        await update_runtime_run(
            db,
            str(run.id),
            status=terminal_status,
            message=duplicate_messages.get(
                result.get("outcome"),
                "Sequential source-unit ingestion completed successfully.",
            ),
            stats=persisted_stats,
            finished_at=datetime.now(timezone.utc),
            attempt_event=_runtime_attempt_event(
                run,
                terminal_status.value,
                result=result,
                message="Sequential source-unit ingestion completed successfully.",
            ),
        )
    else:
        terminal_status = PartnerRuntimeRunStatus.FAILED
        await update_runtime_run(
            db,
            str(run.id),
            status=terminal_status,
            message=result.get("error") or "Source-unit ingestion failed.",
            stats=persisted_stats,
            finished_at=datetime.now(timezone.utc),
            attempt_event=_runtime_attempt_event(
                run,
                terminal_status.value,
                result=result,
                message=result.get("error"),
            ),
        )
    return {
        "success": result.get("success", False),
        "stage": "ingestion" if result.get("processed", 0) else "fetch",
        "partner": partner,
        **result,
        "stats": persisted_stats,
        "runtimeRun": {
            "id": str(run.id),
            "status": (
                PartnerRuntimeRunStatus.WAITING_REVIEW.value
                if waiting_for_review
                else PartnerRuntimeRunStatus.COMPLETED.value
                if result.get("success")
                else PartnerRuntimeRunStatus.FAILED.value
            ),
            "outcome": result.get("outcome"),
        },
    }


async def run_fetch_config_once(
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
        run = await PartnerRuntimeRunRepository(db).find_one({"_id": runtime_run_id})
        if run is None:
            raise ValueError(f"Runtime run '{runtime_run_id}' was not found.")
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
            attempt_event=_runtime_attempt_event(
                run,
                "STARTED",
                message="Fetching source units sequentially.",
            ),
        )
    identity = _stream_identity(
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
        return await _finish_source_stream_run(
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
                "checkpoint": _checkpoint_result(checkpoint),
            },
            stats={"totalRows": 0, "successRows": 0, "duplicateRows": 0, "failedRows": 0, "unitsProcessed": 0},
        )
    if checkpoint and checkpoint.stream_ended:
        return await _finish_source_stream_run(
            db=db,
            run=run,
            partner=config.partner,
            result={
                "success": True,
                "processed": 0,
                "failed": 0,
                "reconciliationSkipped": True,
                "streamAlreadyCompleted": True,
                "checkpoint": _checkpoint_result(checkpoint),
            },
            stats={"totalRows": 0, "successRows": 0, "duplicateRows": 0, "failedRows": 0, "unitsProcessed": 0},
        )

    fetcher = create_fetcher(config)
    async def cleanup_unit(unit: SourceUnitMetadata) -> None:
        await _cleanup_source_unit(config, unit)

    ingest_unit, stats = _build_source_unit_ingestor(
        config=config,
        db=db,
        config_loader=config_loader,
        partner=config.partner,
        reconciliation_date=reconciliation_date,
        batch_size=batch_size,
        structured_logger=structured_logger,
        reconciliation_run_id=str(run.id),
        mapping_config_version=mapping_config_version,
    )
    retry_policy = RetryPolicy()
    raw_page_repo = RawIngestionPageRepository(db)
    raw_stage_key = (
        _raw_stage_key(config, reconciliation_date)
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

                        async def fetch_failure(_: dict[str, Any]) -> dict[str, Any]:
                            error_code = failed_unit.error_code or (
                                "fetch_http_4xx"
                                if "status 4" in (fetch_result.error or "")
                                else "fetch_http_5xx"
                                if "status 5" in (fetch_result.error or "")
                                else "fetch_network_error"
                            )
                            return _ingestion_error_result(
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
                        return await _finish_source_stream_run(
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
                    return await _finish_source_stream_run(
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
                unit.high_water_mark = _unit_high_water_mark(unit)
                unit.fetch_metadata = {
                    **unit.fetch_metadata,
                    "rawStageKey": raw_stage_key,
                }
                if raw_staging_available:
                    try:
                        await raw_page_repo.stage_from_path(
                            stage_key=raw_stage_key,
                            partner=identity["partner"],
                            fetch_config_id=identity["fetchConfigId"],
                            source_type=identity["sourceType"],
                            stream_key=identity["streamKey"],
                            reconciliation_date=reconciliation_date,
                            unit=unit,
                        )
                    except TypeError as exc:
                        # Test doubles and legacy adapters may not expose a
                        # Motor database. Keep their existing execution path;
                        # real deployments fail loudly for storage/network
                        # errors rather than silently dropping raw pages.
                        if (
                            "must be MotorDatabase" not in str(exc)
                            and "can't be used in 'await' expression" not in str(exc)
                        ):
                            raise
                        raw_staging_available = False
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
                        return await _finish_source_stream_run(
                            db=db, run=run, partner=config.partner, result=unit_result, stats=stats
                        )
                    if not fetch_result.metadata["pagination"].get("has_more"):
                        return await _finish_source_stream_run(
                            db=db, run=run, partner=config.partner, result=unit_result, stats=stats
                        )
                    previous_unit_key = unit.source_unit_key
                    fetch_metadata = {
                        "singleUnit": True,
                        "page": unit.page + 1,
                        "cursor": unit.cursor_after,
                        "configVersion": identity["configVersion"],
                    }
                    continue
                if not fetch_result.metadata["pagination"].get("has_more"):
                    break
                previous_unit_key = unit.source_unit_key
                fetch_metadata = {
                    "singleUnit": True,
                    "page": unit.page + 1,
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
                    active_runtime_config = await check_and_refresh_config(
                        file_path=first_staged_unit.local_path or "",
                        partner=config.partner,
                        workflow_type="UPC",
                        file_type=FileType.SETTLEMENT,
                        config_loader=config_loader,
                        config_repo=MappingConfigRepository(db),
                        source_file_name=Path(first_staged_unit.local_path or "").name,
                        source_file_path=first_staged_unit.local_path,
                        reconciliation_date=reconciliation_date,
                        raw_stage_key=raw_stage_key,
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
                        "rawStageKey": raw_stage_key,
                    }
                    return await _finish_source_stream_run(
                        db=db,
                        run=run,
                        partner=config.partner,
                        result=review_result,
                        stats=stats,
                    )
                except Exception as exc:
                    logger.warning(
                        "Preflight mapping check failed for staged stream %s: %s",
                        raw_stage_key,
                        exc,
                    )

                if active_runtime_config is not None:
                    await create_stream_scope_review_packet(
                        database=db,
                        partner=config.partner,
                        file_type=FileType.SETTLEMENT,
                        active_runtime_config=active_runtime_config,
                        source_file_name=Path(first_staged_unit.local_path or "").name,
                        source_file_path=first_staged_unit.local_path,
                        reconciliation_date=reconciliation_date,
                        raw_stage_key=raw_stage_key,
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
                    return await _finish_source_stream_run(
                        db=db,
                        run=run,
                        partner=config.partner,
                        result={
                            "success": True, "processed": 0, "failed": 0,
                            "fetchedUnitCount": len(staged_units), "totalUnitCount": len(staged_units),
                            "stoppedAt": first_staged_unit.source_unit_key,
                            "outcome": "WAITING_REVIEW", "waitingForReview": True,
                            "rawStageKey": raw_stage_key,
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
            return await _finish_source_stream_run(
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
                return await _finish_source_stream_run(
                    db=db,
                    run=run,
                    partner=config.partner,
                    result={"success": True, "processed": 0, "failed": 0, "outcome": "NO_NEW_FILE"},
                    stats=stats,
                )
            return await _finish_source_stream_run(
                db=db,
                run=run,
                partner=config.partner,
                result={"success": False, "processed": 0, "failed": 1, "error": fetch_result.error},
                stats=stats,
            )

        fetched_units = _source_units(fetch_result.units or [])
        units = _units_after_checkpoint(fetched_units, checkpoint)
        if fetched_units and not units:
            return await _finish_source_stream_run(
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
            return await _finish_source_stream_run(
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
                **({"rawStageKey": raw_stage_key} if raw_stage_key else {}),
            }
            unit.high_water_mark = _unit_high_water_mark(unit)
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
        return await _finish_source_stream_run(
            db=db, run=run, partner=config.partner, result=result, stats=stats
        )
    except Exception as exc:
        summarized_error = summarize_runtime_error(exc)
        failed_result = await _finish_source_stream_run(
            db=db,
            run=run,
            partner=config.partner,
            result={"success": False, "processed": 0, "failed": 1, "error": summarized_error},
            stats=stats,
        )
        if raise_on_unexpected:
            raise
        return failed_result


async def daily_partner_fetch_job(
    db: Any = None,
    config_loader: Any = None,
    batch_size: int = 100,
    structured_logger: Optional[StructuredLogger] = None,
) -> dict:
    """Daily job to fetch data from all enabled partners and ingest.

    Flow:
    1. Query fetch_config collection for enabled partners
    2. For each partner:
       - Create appropriate fetcher based on fetch_method
       - Fetch data from partner
       - If success → trigger IngestionPipeline.process_file()
       - Handle cleanup/archive based on config
    3. Aggregate results and emit log events

    Args:
        db: AsyncIOMotorDatabase instance.
        config_loader: ConfigLoader for loading mapping configurations.
        batch_size: Batch size for ingestion pipeline.
        structured_logger: Optional logger for structured events.

    Returns:
        Dict with aggregate results (total, success, failed).
    """
    if db is None:
        from motor.motor_asyncio import AsyncIOMotorClient
        from src.config.settings import settings
        client = AsyncIOMotorClient(settings.mongodb_url)
        db = client[settings.db_name]

    if config_loader is None:
        from src.config.loader import ConfigLoader
        from src.config.cache import ConfigCache
        from src.config.validator import ConfigValidator
        from src.infrastructure.mapping.config_repository import MappingConfigRepository
        config_repo = MappingConfigRepository(db)
        config_cache = ConfigCache()
        config_validator = ConfigValidator()
        config_loader = ConfigLoader(config_repo, config_cache, config_validator)

    if structured_logger is None:
        from src.logging.logger import StructuredLogger
        structured_logger = StructuredLogger()

    fetch_repo = FetchConfigRepository(db)
    try:
        await RawIngestionPageRepository(db).cleanup_expired()
    except Exception:
        logger.warning("Raw page retention cleanup failed", exc_info=True)
    enabled_configs = await fetch_repo.find_enabled()

    if not enabled_configs:
        logger.info("No enabled fetch configs found. Skipping daily job.")
        return {"total": 0, "success": 0, "failed": 0}

    results = {"total": len(enabled_configs), "success": 0, "failed": 0}
    reconciliation_date = _current_business_day_start()

    for config in enabled_configs:
        run_result = await run_fetch_config_once(
            config=config,
            db=db,
            config_loader=config_loader,
            reconciliation_date=reconciliation_date,
            batch_size=batch_size,
            structured_logger=structured_logger,
        )
        if run_result["success"]:
            results["success"] += 1
        else:
            results["failed"] += 1

    logger.info(
        "Daily job completed: total=%d, success=%d, failed=%d",
        results["total"],
        results["success"],
        results["failed"],
    )

    return results


async def _run_ingestion(
    db: Any,
    config_loader: ConfigLoader,
    file_path: str,
    partner: str,
    reconciliation_date: datetime,
    batch_size: int | None = None,
    structured_logger: Optional[StructuredLogger] = None,
    fetch_unit_metadata: Optional[dict[str, Any]] = None,
    config_version: Optional[str] = None,
    enable_config_health_check: bool = True,
    validate_rows: bool = False,
) -> Any:
    """Run the ingestion pipeline for a fetched file.

    Args:
        db: AsyncIOMotorDatabase instance.
        config_loader: ConfigLoader for loading mapping configurations.
        file_path: Path to the fetched file.
        partner: Partner identifier.
        reconciliation_date: Date of the reconciliation file.
        batch_size: Batch size for ingestion pipeline (None = use settings default).
        structured_logger: Optional logger for structured events.

    Returns:
        IngestionResult or None if ingestion failed.
    """
    try:
        pipeline = build_ingestion_pipeline(
            db=db,
            config_loader=config_loader,
            batch_size=batch_size,
            logger=structured_logger,
            fast_mode=not validate_rows,
        )

        result = await pipeline.process_file(
            file_path=file_path,
            partner=partner,
            workflow_type="UPC",
            file_type=FileType.SETTLEMENT,
            reconciliation_date=reconciliation_date,
            config_version=config_version,
            fetch_unit_metadata=fetch_unit_metadata,
            enable_config_health_check=enable_config_health_check,
        )

        logger.info(
            "Ingestion completed for %s: status=%s, total=%d, success=%d, failed=%d",
            partner,
            result.file_record.processing_status,
            result.stats.total_rows,
            result.stats.success_rows,
            result.stats.failed_rows,
        )

        if structured_logger:
            structured_logger.get_logger().info(
                "INGESTION_TRIGGERED",
                extra={
                    "partner": partner,
                    "file_path": file_path,
                    "status": result.file_record.processing_status,
                },
            )

        return result

    except Exception as exc:
        logger.error(
            "Ingestion failed for %s: %s",
            partner,
            exc,
            exc_info=True,
        )
        return None
