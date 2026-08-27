"""Application use cases for ingesting and reconciling fetched source units."""

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Optional

from src.application.ingestion.contracts import IngestionResult, ProcessFileCommand
from src.application.reconciliation.service import ReconciliationCommand
from src.application.automation.stream_identity import fetch_source_endpoint
from src.config.loader import ConfigLoader
from src.core.enums import FileType, ProcessingStatus
from src.domain.fetch_config.models import FetchConfig, FetchMethod
from src.domain.ingestion.source_units import SourceUnitMetadata
from src.fetchers.base import BaseFetcher
from src.infrastructure.ingestion.composition import build_ingestion_pipeline
from src.infrastructure.reconciliation.composition import build_reconciliation_service
from src.application.ingestion.error_classification import is_missing_ingestion_key_failure
from src.application.ingestion.source_unit_orchestrator import resume_held_source_unit
from src.logging import StructuredLogger

logger = logging.getLogger("reconciliation.automation.stream_ingestion")

__all__ = ["resume_held_source_unit"]


def bounded_source_unit_result(result: Any) -> dict[str, Any]:
    """Serialize both the current result and legacy lightweight test doubles."""

    serializer = getattr(result, "bounded_source_unit_result", None)
    if callable(serializer):
        return serializer()
    quality_decision = getattr(result, "quality_decision", "PASS")
    quality_decision = getattr(quality_decision, "value", quality_decision)
    orchestration_action = getattr(result, "orchestration_action", "CONTINUE")
    orchestration_action = getattr(orchestration_action, "value", orchestration_action)
    quality_summary = getattr(result, "quality_summary", None)
    top_rule_codes = list(getattr(quality_summary, "top_rule_codes", []) or [])
    return {
        "success": getattr(result, "outcome", "INGESTED") != "FAILED",
        "outcome": getattr(result, "outcome", "INGESTED"),
        "qualityDecision": quality_decision,
        "orchestrationAction": orchestration_action,
        "qualityCounters": dict(getattr(result, "quality_counters", {}) or {}),
        "topRuleCodes": top_rule_codes[:10],
    }


def fetch_unit_metadata(
    config: FetchConfig,
    fetch_metadata: dict[str, Any],
    reconciliation_date: datetime,
) -> dict[str, Any]:
    metadata = {
        **fetch_metadata,
        "sourceEndpoint": fetch_source_endpoint(config),
        "windowStart": reconciliation_date.isoformat(),
        "windowEnd": reconciliation_date.isoformat(),
    }
    if config.fetch_method == FetchMethod.FILEDROP:
        metadata["cursor"] = fetch_metadata.get("selected_file")
    return metadata


def ingestion_error_result(
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


def failed_ingestion_result(result: Any) -> dict[str, Any]:
    """Translate a failed file result into a precise source-unit error."""
    stats = getattr(result, "stats", None)
    errors = getattr(result, "errors", None) or []
    if stats is not None and is_missing_ingestion_key_failure(
        total_rows=getattr(stats, "total_rows", 0),
        success_rows=getattr(stats, "success_rows", 0),
        failed_rows=getattr(stats, "failed_rows", 0),
        errors=errors,
    ):
        return ingestion_error_result(
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
    return ingestion_error_result(
        error,
        error_code,
        retryable=False if is_read_failure else None,
    )


async def cleanup_source_unit(config: FetchConfig, unit: SourceUnitMetadata) -> None:
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


def build_source_unit_ingestor(
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
    backfill_run_id: str | None = None,
    config_health_check_enabled: bool = True,
) -> tuple[Callable[[SourceUnitMetadata], Awaitable[dict[str, Any]]], dict[str, int]]:
    stats = {
        "totalRows": 0,
        "successRows": 0,
        "duplicateRows": 0,
        "failedRows": 0,
        "unitsProcessed": 0,
        "reconciliationCount": 0,
    }
    is_paginated_api = (
        config.fetch_method == FetchMethod.API and config.get_method_config().pagination is not None
    )
    config_health_checked = False

    async def ingest_unit(unit: SourceUnitMetadata) -> dict[str, Any]:
        nonlocal config_health_checked
        unit = SourceUnitMetadata.from_payload(unit)
        file_path = unit.local_path
        if not file_path:
            return ingestion_error_result(
                "Source unit is missing localPath", "source_persist_error"
            )

        unit_payload = unit.model_dump(by_alias=True)
        # ``fetchMetadata`` is a nested field in the Pydantic model. Merge the
        # fetcher's bounded page sample after the model dump so it is not
        # overwritten by the model's default empty mapping.
        unit_payload.update(unit.fetch_metadata)
        unit_metadata = fetch_unit_metadata(
            config,
            unit_payload,
            reconciliation_date,
        )
        result = await run_ingestion(
            db=db,
            config_loader=config_loader,
            file_path=file_path,
            partner=partner,
            reconciliation_date=reconciliation_date,
            batch_size=batch_size,
            structured_logger=structured_logger,
            fetch_unit_metadata=unit_metadata,
            config_version=mapping_config_version,
            backfill_run_id=backfill_run_id,
            enable_config_health_check=(
                config_health_check_enabled and (not config_health_checked or not is_paginated_api)
            ),
            validate_rows=config.validate_rows,
        )
        if not result:
            return ingestion_error_result(
                "Ingestion pipeline did not return a file record.",
                "source_persist_error",
            )
        file_record = result.file_record
        if file_record is None:
            return ingestion_error_result(
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
            bounded = bounded_source_unit_result(result)
            return {
                **bounded,
                "success": True,
                "outcome": outcome,
                "duplicateCode": getattr(result, "duplicate_code", None),
            }

        if is_paginated_api:
            config_health_checked = True

        processing_status = getattr(
            file_record.processing_status,
            "value",
            file_record.processing_status,
        )
        orchestration_action = getattr(
            getattr(result, "orchestration_action", "CONTINUE"),
            "value",
            getattr(result, "orchestration_action", "CONTINUE"),
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
            failure = failed_ingestion_result(result)
            if orchestration_action == "FAIL":
                return {
                    **failure,
                    **bounded_source_unit_result(result),
                    "success": False,
                    "outcome": "FAILED",
                }
            return failure

        bounded = bounded_source_unit_result(result)
        if orchestration_action == "HOLD_FOR_REVIEW":
            return {
                **bounded,
                "success": True,
                "outcome": "INGESTED",
                "reconciliationSkipped": True,
            }

        reconciliation_results = await build_reconciliation_service(db, fast_mode=True).execute(
            ReconciliationCommand(
                partner=partner,
                reconciliation_date=reconciliation_date,
                source_file_id=str(file_record.id),
                reconciliation_run_id=reconciliation_run_id,
            )
        )
        stats["reconciliationCount"] += len(reconciliation_results)
        return {
            **bounded,
            "success": True,
            "outcome": "INGESTED",
            "reconciliationCount": len(reconciliation_results),
        }

    return ingest_unit, stats


async def run_ingestion(
    db: Any,
    config_loader: ConfigLoader,
    file_path: str,
    partner: str,
    reconciliation_date: datetime,
    batch_size: int | None = None,
    structured_logger: Optional[StructuredLogger] = None,
    fetch_unit_metadata: Optional[dict[str, Any]] = None,
    config_version: Optional[str] = None,
    backfill_run_id: Optional[str] = None,
    enable_config_health_check: bool = True,
    validate_rows: bool = False,
) -> IngestionResult | None:
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

        result = await pipeline.execute(
            ProcessFileCommand(
                file_path=file_path,
                partner=partner,
                workflow_type="UPC",
                file_type=FileType.SETTLEMENT,
                reconciliation_date=reconciliation_date,
                config_version=config_version,
                backfill_run_id=backfill_run_id,
                fetch_unit_metadata=fetch_unit_metadata,
                enable_config_health_check=enable_config_health_check,
            )
        )
        file_record = result.file_record
        if file_record is None:
            logger.error("Ingestion completed without a source file record for %s", partner)
            return None

        logger.info(
            "Ingestion completed for %s: status=%s, total=%d, success=%d, failed=%d",
            partner,
            file_record.processing_status,
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
                    "status": file_record.processing_status,
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
