"""Daily fetch job definitions.

Defines the job that runs at scheduled times to fetch data from all enabled
partners and trigger the ingestion pipeline.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from src.config.loader import ConfigLoader
from src.core.enums import FileType, ProcessingStatus
from src.fetchers import create_fetcher
from src.fetchers.base import FetchResult
from src.logging import StructuredLogger
from src.models.fetch_config import FetchConfig, FetchConfigRepository
from src.pipeline.ingestion_pipeline import IngestionPipeline

logger = logging.getLogger("reconciliation.jobs")


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
        from src.models.mapping_config import MappingConfigRepository
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


async def run_fetch_config_once(
    config: FetchConfig,
    db: Any,
    config_loader: Any,
    reconciliation_date: datetime,
    batch_size: int = 100,
    structured_logger: Optional[StructuredLogger] = None,
) -> dict[str, Any]:
    """Execute one enabled fetch config immediately.

    Returns a compact result suitable for API/admin visibility.
    """
    partner = config.partner
    logger.info("Processing partner: %s (method=%s)", partner, config.fetch_method)

    try:
        fetcher = create_fetcher(config)
        fetch_result = await fetcher.fetch(config.get_method_config(), reconciliation_date)

        if not fetch_result.success:
            logger.error("Fetch failed for %s: %s", partner, fetch_result.error)
            if structured_logger:
                structured_logger.get_logger().info(
                    "FETCH_FAILED",
                    extra={"partner": partner, "error": fetch_result.error},
                )
            return {
                "success": False,
                "stage": "fetch",
                "partner": partner,
                "error": fetch_result.error,
            }

        logger.info(
            "Fetch success for %s: %s (%d bytes)",
            partner,
            fetch_result.local_path,
            fetch_result.file_size,
        )
        if structured_logger:
            structured_logger.get_logger().info(
                "FETCH_SUCCESS",
                extra={
                    "partner": partner,
                    "file_path": fetch_result.local_path,
                    "file_size": fetch_result.file_size,
                },
            )

        ingestion_result = await _run_ingestion(
            db=db,
            config_loader=config_loader,
            file_path=fetch_result.local_path,
            partner=partner,
            reconciliation_date=reconciliation_date,
            batch_size=batch_size,
            structured_logger=structured_logger,
        )
        if not ingestion_result or not ingestion_result.file_record:
            return {
                "success": False,
                "stage": "ingestion",
                "partner": partner,
                "error": "Ingestion pipeline did not return a file record.",
            }

        processing_status = getattr(
            ingestion_result.file_record.processing_status,
            "value",
            ingestion_result.file_record.processing_status,
        )

        if config.cleanup_after_ingest and processing_status == ProcessingStatus.COMPLETED.value:
            if config.archive_dir:
                archived_path = BaseFetcher.archive_file(
                    fetch_result.local_path,
                    config.archive_dir,
                    config.archive_retention_days,
                )
                if archived_path:
                    logger.info("Archived file for %s: %s", partner, archived_path)
            else:
                BaseFetcher.cleanup_file(fetch_result.local_path)
                logger.info("Cleaned up file for %s: %s", partner, fetch_result.local_path)

        return {
            "success": True,
            "partner": partner,
            "filePath": fetch_result.local_path,
            "fileSize": fetch_result.file_size,
            "processingStatus": processing_status,
        }

    except Exception as exc:
        logger.error("Unexpected error processing %s: %s", partner, exc, exc_info=True)
        if structured_logger:
            structured_logger.get_logger().info(
                "JOB_FAILED",
                extra={"partner": partner, "error": str(exc)},
            )
        return {
            "success": False,
            "stage": "unexpected",
            "partner": partner,
            "error": str(exc),
        }


async def _run_ingestion(
    db: Any,
    config_loader: ConfigLoader,
    file_path: str,
    partner: str,
    reconciliation_date: datetime,
    batch_size: int = 100,
    structured_logger: Optional[StructuredLogger] = None,
) -> Any:
    """Run the ingestion pipeline for a fetched file.

    Args:
        db: AsyncIOMotorDatabase instance.
        config_loader: ConfigLoader for loading mapping configurations.
        file_path: Path to the fetched file.
        partner: Partner identifier.
        reconciliation_date: Date of the reconciliation file.
        batch_size: Batch size for ingestion pipeline.
        structured_logger: Optional logger for structured events.

    Returns:
        IngestionResult or None if ingestion failed.
    """
    try:
        from src.pipeline.ingestion_pipeline import IngestionPipeline

        pipeline = IngestionPipeline(
            db=db,
            config_loader=config_loader,
            batch_size=batch_size,
            logger=structured_logger,
        )

        result = await pipeline.process_file(
            file_path=file_path,
            partner=partner,
            workflow_type="UPC",
            file_type=FileType.SETTLEMENT,
            reconciliation_date=reconciliation_date,
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
