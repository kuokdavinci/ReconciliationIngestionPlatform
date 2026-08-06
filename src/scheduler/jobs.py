"""Daily fetch job definitions.

Defines the job that runs at scheduled times to fetch data from all enabled
partners and trigger the ingestion pipeline.
"""

import logging
from datetime import datetime, timezone
from collections.abc import Sequence
from typing import Any, Optional

from src.config.loader import ConfigLoader
from src.core.enums import FileType, ProcessingStatus
from src.core.error_formatting import summarize_runtime_error
from src.fetchers import create_fetcher
from src.fetchers.base import BaseFetcher
from src.logging import StructuredLogger
from src.domain.fetch_config.models import FetchConfig, FetchMethod
from src.infrastructure.fetch_config.repository import FetchConfigRepository
from src.domain.ingestion.checkpoints import CheckpointStatus, IngestionMode
from src.infrastructure.ingestion.checkpoint_repository import IngestionCheckpointRepository
from src.infrastructure.runtime.repository import PartnerRuntimeRunRepository
from src.domain.ingestion.source_units import SourceUnitMetadata
from src.application.reconciliation.service import ReconciliationCommand
from src.infrastructure.reconciliation.composition import build_reconciliation_service
from src.infrastructure.ingestion.composition import build_ingestion_pipeline
from src.services.runtime_runs import create_runtime_run, update_runtime_run
from src.services.retry_policy import RetryPolicy
from src.application.ingestion.source_unit_orchestrator import process_source_units
from src.domain.runtime.models import (
    PartnerRuntimeRunStatus,
    PartnerRuntimeTriggerType,
)

logger = logging.getLogger("reconciliation.jobs")


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


def _stream_identity(config: FetchConfig) -> dict[str, Any]:
    return {
        "partner": config.partner,
        "fetchConfigId": str(config.id),
        "sourceType": config.fetch_method.value,
        "streamKey": _source_stream_key(config),
        "configVersion": str(config.updated_at),
        "sourceEndpoint": _fetch_source_endpoint(config),
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
) -> tuple[Any, dict[str, int]]:
    stats = {
        "totalRows": 0,
        "successRows": 0,
        "duplicateRows": 0,
        "failedRows": 0,
        "unitsProcessed": 0,
    }

    async def ingest_unit(unit: SourceUnitMetadata | dict[str, Any]) -> dict[str, Any]:
        unit = SourceUnitMetadata.from_payload(unit)
        file_path = unit.local_path
        if not file_path:
            return _ingestion_error_result(
                "Source unit is missing localPath", "source_persist_error"
            )

        unit_metadata = _fetch_unit_metadata(
            config,
            {
                **unit.fetch_metadata,
                **unit.model_dump(by_alias=True),
            },
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
            return _ingestion_error_result(
                "Ingestion failed.",
                "source_persist_error",
            )

        reconciliation_results = await build_reconciliation_service(db, fast_mode=True).execute(
            ReconciliationCommand(
                partner=partner,
                reconciliation_date=reconciliation_date,
                source_file_id=str(result.file_record.id),
            )
        )
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
    }
    waiting_for_review = (
        result.get("outcome") == "WAITING_REVIEW"
        or result.get("waitingForReview") is True
    )
    if waiting_for_review:
        await update_runtime_run(
            db,
            str(run.id),
            status=PartnerRuntimeRunStatus.WAITING_REVIEW,
            message=result.get("error")
            or "A draft mapping is waiting for review before ingestion can continue.",
            stats={**stats, **result},
            finished_at=datetime.now(timezone.utc),
        )
    elif result.get("success"):
        await update_runtime_run(
            db,
            str(run.id),
            status=PartnerRuntimeRunStatus.COMPLETED,
            message=duplicate_messages.get(
                result.get("outcome"),
                "Sequential source-unit ingestion completed successfully.",
            ),
            stats={**stats, **result},
            finished_at=datetime.now(timezone.utc),
        )
    else:
        await update_runtime_run(
            db,
            str(run.id),
            status=PartnerRuntimeRunStatus.FAILED,
            message=result.get("error") or "Source-unit ingestion failed.",
            stats={**stats, **result},
            finished_at=datetime.now(timezone.utc),
        )
    return {
        "success": result.get("success", False),
        "stage": "ingestion" if result.get("processed", 0) else "fetch",
        "partner": partner,
        **result,
        "stats": stats,
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
        )
    else:
        run = await PartnerRuntimeRunRepository(db).find_one({"_id": runtime_run_id})
        if run is None:
            raise ValueError(f"Runtime run '{runtime_run_id}' was not found.")
        await update_runtime_run(
            db,
            str(run.id),
            status=PartnerRuntimeRunStatus.FETCHING,
            message="Fetching source units sequentially.",
        )
    identity = _stream_identity(config)
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
                "processed": 0,
                "failed": 1,
                "stoppedAt": checkpoint.current_unit_key,
                "error": "Source stream is BLOCKED and requires operator resolution.",
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
    )
    retry_policy = RetryPolicy()
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

            while True:
                fetch_result = await fetcher.fetch(
                    method_config,
                    reconciliation_date,
                    fetch_metadata=fetch_metadata,
                )
                if not fetch_result.success:
                    if fetch_result.units:
                        failed_unit = SourceUnitMetadata.from_payload(fetch_result.units[-1])

                        async def fetch_failure(_: dict[str, Any]) -> dict[str, Any]:
                            error_code = failed_unit.error_code or (
                                "fetch_http_4xx"
                                if "status 4" in (fetch_result.error or "")
                                else "fetch_network_error"
                            )
                            return _ingestion_error_result(
                                fetch_result.error or "API source unit fetch failed",
                                error_code,
                                retryable=retry_policy.classify(error_code).value == "RETRYABLE",
                            )

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
                        return await _finish_source_stream_run(
                            db=db, run=run, partner=config.partner, result=failed_result, stats=stats
                        )
                    return await _finish_source_stream_run(
                        db=db,
                        run=run,
                        partner=config.partner,
                        result={"success": False, "processed": 0, "failed": 1, "error": fetch_result.error},
                        stats=stats,
                    )

                unit = SourceUnitMetadata.from_payload(fetch_result.units[0])
                unit.high_water_mark = _unit_high_water_mark(unit)
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
                if not unit_result["success"]:
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
            unit.fetch_metadata = fetch_result.metadata
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
        return await _finish_source_stream_run(
            db=db,
            run=run,
            partner=config.partner,
            result={"success": False, "processed": 0, "failed": 1, "error": summarized_error},
            stats=stats,
        )


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
    enabled_configs = await fetch_repo.find_enabled()

    if not enabled_configs:
        logger.info("No enabled fetch configs found. Skipping daily job.")
        return {"total": 0, "success": 0, "failed": 0}

    results = {"total": len(enabled_configs), "success": 0, "failed": 0}
    reconciliation_date = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

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
            fast_mode=True,
        )

        result = await pipeline.process_file(
            file_path=file_path,
            partner=partner,
            workflow_type="UPC",
            file_type=FileType.SETTLEMENT,
            reconciliation_date=reconciliation_date,
            fetch_unit_metadata=fetch_unit_metadata,
            enable_config_health_check=True,
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
