"""Post-approval run lifecycle and file-level reconciliation service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Optional

from src.analysis.insights import invalidate_insight_cache
from src.application.reconciliation.service import ReconciliationCommand
from src.application.review.raw_stream import resolve_review_source_file
from src.application.runtime.service import create_runtime_run, update_runtime_run
from src.config.settings import settings
from src.core.business_day import business_date
from src.core.error_formatting import summarize_runtime_error
from src.core.enums import ProcessingStatus, ReconciliationScopeType
from src.domain.review.models import (
    PostApprovalRun,
    PostApprovalRunStage,
    PostApprovalRunStatus,
)
from src.domain.runtime.models import PartnerRuntimeRunStatus, PartnerRuntimeTriggerType
from src.infrastructure.ingestion.composition import build_ingestion_pipeline
from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository
from src.infrastructure.mapping.composition import build_config_loader
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.infrastructure.partner_transaction.repository import DataContainerRepository
from src.infrastructure.postgres.reconciliation_result_repository import (
    ReconciliationResultRepository,
)
from src.infrastructure.reconciliation.composition import build_reconciliation_service
from src.infrastructure.review.repository import (
    PostApprovalRunRepository,
    ReviewPacketRepository,
)


ScheduleBackground = Callable[[Awaitable[None]], None]


async def rebind_replacement_transactions(
    *,
    db: Any,
    packet: Any,
    config: Any,
    ingestion_result: Any,
    source_file_id: str,
    transaction_repo_factory: Callable[[Any], Any] = DataContainerRepository,
) -> int:
    """Attach deduplicated replacement rows to the current logical file."""
    scope_type = getattr(packet, "scope_type", None)
    scope_type = getattr(scope_type, "value", scope_type)
    if scope_type != ReconciliationScopeType.REPLACEMENT.value:
        return 0

    keys = list(
        dict.fromkeys(
            str(key).strip()
            for key in (getattr(ingestion_result, "ingestion_keys", None) or [])
            if str(key).strip()
        )
    )
    if not keys:
        return 0
    return await transaction_repo_factory(db).rebind_source_file_by_ingestion_keys(
        config.partner,
        keys,
        source_file_id,
    )


def serialize_post_approval_run(run: PostApprovalRun) -> dict[str, Any]:
    data = run.model_dump(by_alias=True)
    data["_id"] = str(data["_id"])
    for key in ("createdAt", "updatedAt", "startedAt", "finishedAt"):
        value = data.get(key)
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return data


async def update_post_approval_run(
    db: Any,
    run_id: str,
    *,
    status: Optional[PostApprovalRunStatus] = None,
    stage: Optional[PostApprovalRunStage] = None,
    message: Optional[str] = None,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
    source_file_id: Optional[str] = None,
    output_file_id: Optional[str] = None,
    reconciliation_count: Optional[int] = None,
    stats: Optional[dict[str, Any]] = None,
    errors: Optional[list[Any]] = None,
    repository_factory: Callable[[Any], Any] = PostApprovalRunRepository,
) -> None:
    update: dict[str, Any] = {"updatedAt": datetime.now(timezone.utc)}
    if status is not None:
        update["status"] = status.value
    if stage is not None:
        update["stage"] = stage.value
    if message is not None:
        update["message"] = message
    if started_at is not None:
        update["startedAt"] = started_at
    if finished_at is not None:
        update["finishedAt"] = finished_at
    if source_file_id is not None:
        update["sourceFileId"] = source_file_id
    if output_file_id is not None:
        update["outputFileId"] = output_file_id
    if reconciliation_count is not None:
        update["reconciliationCount"] = reconciliation_count
    if stats is not None:
        update["stats"] = stats
    if errors is not None:
        update["errors"] = errors
    await repository_factory(db).collection.update_one(
        {"_id": run_id},
        {"$set": update},
    )


async def queue_post_approval_reprocess(
    db: Any,
    packet: Any,
    config: Any,
    *,
    schedule_background: ScheduleBackground,
    run_task: Callable[[Any, str, str, str], Awaitable[None]] | None = None,
    run_repository_factory: Callable[[Any], Any] = PostApprovalRunRepository,
) -> dict[str, Any]:
    """Create and schedule a durable post-approval replay."""
    run = PostApprovalRun(
        packetId=str(packet.id),
        partner=packet.partner,
        date=(
            business_date(packet.reconciliation_date).isoformat()
            if getattr(packet, "reconciliation_date", None)
            else None
        ),
        status=PostApprovalRunStatus.QUEUED,
        stage=PostApprovalRunStage.APPROVAL,
        message="Approved. Post-approval processing is queued.",
        sourceFileId=getattr(packet, "source_file_id", None),
    )
    await run_repository_factory(db).create(run)
    if run_task is None:
        run_task = run_post_approval_reprocess
    schedule_background(run_task(db, str(run.id), str(packet.id), str(config.id)))
    return serialize_post_approval_run(run)


async def run_post_approval_reprocess(
    db: Any,
    run_id: str,
    packet_id: str,
    config_id: str,
    *,
    packet_repository_factory: Callable[[Any], Any] = ReviewPacketRepository,
    config_repository_factory: Callable[[Any], Any] = MappingConfigRepository,
    updater: Callable[..., Awaitable[None]] = update_post_approval_run,
    processor: Callable[..., Awaitable[dict | None]] | None = None,
) -> None:
    packet = await packet_repository_factory(db).find_one({"_id": packet_id})
    config = await config_repository_factory(db).find_one({"_id": config_id})
    if packet is None or config is None:
        await updater(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.APPROVAL,
            message="Packet or approved mapping could not be loaded for post-approval processing.",
            finished_at=datetime.now(timezone.utc),
        )
        return
    try:
        if processor is None:
            processor = reconcile_approved_packet
        await processor(db, packet, config, run_id, updater=updater)
    except Exception as exc:
        summarized_error = summarize_runtime_error(exc)
        await updater(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            message=f"Post-approval processing failed: {summarized_error}",
            finished_at=datetime.now(timezone.utc),
            errors=[summarized_error],
        )


async def reconcile_approved_packet(
    db: Any,
    packet: Any,
    config: Any,
    run_id: str,
    *,
    updater: Callable[..., Awaitable[None]] = update_post_approval_run,
    staged_replayer: Callable[..., Awaitable[dict | None]] | None = None,
    source_resolver: Callable[[Any], Any] = resolve_review_source_file,
    runtime_creator: Callable[..., Awaitable[Any]] = create_runtime_run,
    runtime_updater: Callable[..., Awaitable[None]] = update_runtime_run,
    file_repository_factory: Callable[[Any], Any] = ReconciliationFileRepository,
    transaction_repository_factory: Callable[[Any], Any] = DataContainerRepository,
    result_repository_factory: Callable[[Any], Any] = ReconciliationResultRepository,
    pipeline_builder: Callable[..., Any] = build_ingestion_pipeline,
    config_loader_builder: Callable[[Any], Any] = build_config_loader,
    reconciliation_service_builder: Callable[..., Any] = build_reconciliation_service,
    replacement_rebinder: Callable[..., Awaitable[int]] = rebind_replacement_transactions,
    cache_invalidator: Callable[[str, str], Awaitable[Any]] = invalidate_insight_cache,
) -> dict | None:
    """Replay a review packet source and reconcile its resulting transactions."""
    runtime_run = await runtime_creator(
        db,
        partner=config.partner,
        date=business_date(packet.reconciliation_date).isoformat(),
        trigger_type=PartnerRuntimeTriggerType.POST_APPROVAL_REPROCESS,
        triggered_by="system:post-approval",
        status=PartnerRuntimeRunStatus.INGESTING,
        message="Approved file is queued for ingestion.",
        source_file_id=getattr(packet, "source_file_id", None),
        mapping_version=getattr(config, "config_version", None) or str(getattr(config, "id", "")),
        validation_state="NOT_RUN",
    )
    runtime_run_id = str(runtime_run.id)
    source_file_path = getattr(packet, "source_file_path", None)
    source_file_id = getattr(packet, "source_file_id", None)
    raw_stage_key = getattr(packet, "raw_stage_key", None)
    if raw_stage_key:
        if staged_replayer is None:
            from src.application.review.staged_page_replay import replay_staged_pages

            staged_replayer = replay_staged_pages
        staged_result = await staged_replayer(
            db=db,
            packet=packet,
            config=config,
            run_id=run_id,
            runtime_run_id=runtime_run_id,
            raw_stage_key=raw_stage_key,
            updater=updater,
            runtime_updater=runtime_updater,
            replacement_rebinder=replacement_rebinder,
        )
        if staged_result is not None:
            return staged_result
    if not source_file_path or not source_file_id:
        await runtime_updater(
            db,
            runtime_run_id,
            status=PartnerRuntimeRunStatus.FAILED,
            message="Review packet has no source file attached for post-approval processing.",
            finished_at=datetime.now(timezone.utc),
        )
        await updater(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.APPROVAL,
            message="Review packet has no source file attached for post-approval processing.",
            finished_at=datetime.now(timezone.utc),
        )
        return None

    try:
        resolved_source_path = source_resolver(packet)
    except (FileNotFoundError, ValueError):
        message = f"Source file is no longer available at {source_file_path}."
        await runtime_updater(
            db,
            runtime_run_id,
            status=PartnerRuntimeRunStatus.FAILED,
            message=message,
            finished_at=datetime.now(timezone.utc),
        )
        await updater(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.APPROVAL,
            message=message,
            finished_at=datetime.now(timezone.utc),
        )
        return None

    file_repo = file_repository_factory(db)
    source_file = await file_repo.find_one({"_id": source_file_id})
    if source_file is None:
        message = f"Source file record {source_file_id} was not found."
        await runtime_updater(
            db,
            runtime_run_id,
            status=PartnerRuntimeRunStatus.FAILED,
            message=message,
            finished_at=datetime.now(timezone.utc),
        )
        await updater(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.APPROVAL,
            message=message,
            finished_at=datetime.now(timezone.utc),
        )
        return None

    await transaction_repository_factory(db).delete_by_source_file(source_file_id)
    date_str = business_date(source_file.reconciliation_date).isoformat()
    await result_repository_factory(db).delete_by_partner_and_date(config.partner, date_str)
    if source_file.processing_status != ProcessingStatus.COMPLETED:
        await file_repo.delete_one({"_id": source_file_id})

    await updater(
        db,
        run_id,
        status=PostApprovalRunStatus.INGESTING,
        stage=PostApprovalRunStage.INGESTION,
        message="Ingesting partner file with the approved mapping.",
        started_at=datetime.now(timezone.utc),
    )
    await runtime_updater(
        db,
        runtime_run_id,
        status=PartnerRuntimeRunStatus.INGESTING,
        message="Ingesting partner file with the approved mapping.",
        started_at=datetime.now(timezone.utc),
    )

    pipeline = pipeline_builder(
        db=db,
        config_loader=config_loader_builder(db),
        batch_size=settings.ingest_batch_size,
        logger=None,
        fast_mode=True,
    )
    ingestion_result = await pipeline.process_file(
        file_path=str(resolved_source_path),
        partner=config.partner,
        workflow_type=config.workflow_type,
        file_type=config.file_type,
        reconciliation_date=source_file.reconciliation_date,
        config_version=config.config_version,
        fetch_unit_metadata={
            "sourceEndpoint": f"review://{source_file_id}",
            "cursor": f"post-approval:{run_id}",
            "windowStart": source_file.reconciliation_date.isoformat(),
            "windowEnd": source_file.reconciliation_date.isoformat(),
        },
        enable_config_health_check=False,
    )
    file_record = ingestion_result.file_record
    if file_record is None:
        raise RuntimeError("Ingestion did not return a source file record.")
    processing_status = getattr(file_record.processing_status, "value", file_record.processing_status)
    if processing_status == ProcessingStatus.COMPLETED.value:
        await replacement_rebinder(
            db=db,
            packet=packet,
            config=config,
            ingestion_result=ingestion_result,
            source_file_id=str(file_record.id),
        )
    result = {
        "ok": processing_status == ProcessingStatus.COMPLETED.value,
        "stage": "ingestion",
        "partner": config.partner,
        "date": business_date(source_file.reconciliation_date).isoformat(),
        "processingStatus": processing_status,
        "fileId": str(file_record.id),
        "stats": {
            "totalRows": ingestion_result.stats.total_rows,
            "successRows": ingestion_result.stats.success_rows,
            "duplicateRows": ingestion_result.stats.duplicate_rows,
            "failedRows": ingestion_result.stats.failed_rows,
        },
        "errors": ingestion_result.errors,
    }
    if processing_status != ProcessingStatus.COMPLETED.value:
        await runtime_updater(
            db,
            runtime_run_id,
            status=PartnerRuntimeRunStatus.FAILED,
            message="Ingestion failed after approval.",
            source_file_id=str(file_record.id),
            stats=result["stats"],
            finished_at=datetime.now(timezone.utc),
        )
        await updater(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.INGESTION,
            message="Ingestion failed after approval.",
            finished_at=datetime.now(timezone.utc),
            output_file_id=str(file_record.id),
            stats=result["stats"],
            errors=ingestion_result.errors,
        )
        return result

    if packet.scope_type:
        await file_repo.update_one({"_id": str(file_record.id)}, {"scopeType": packet.scope_type})
    await updater(
        db,
        run_id,
        status=PostApprovalRunStatus.RECONCILING,
        stage=PostApprovalRunStage.RECONCILIATION,
        message="Reconciling ingested partner rows against internal transactions.",
        output_file_id=str(file_record.id),
        stats=result["stats"],
        errors=ingestion_result.errors,
    )
    await runtime_updater(
        db,
        runtime_run_id,
        status=PartnerRuntimeRunStatus.RECONCILING,
        message="Reconciling ingested partner rows against internal transactions.",
        source_file_id=str(file_record.id),
        stats=result["stats"],
    )
    recon_results = await reconciliation_service_builder(db, fast_mode=True).execute(
        ReconciliationCommand(
            partner=config.partner,
            reconciliation_date=source_file.reconciliation_date,
            source_file_id=str(file_record.id),
            reconciliation_run_id=runtime_run_id,
            mapping_version=getattr(config, "config_version", None) or str(config.id),
        )
    )
    result_count = len(recon_results)
    result_stats = {**result["stats"], "resultCount": result_count, "reconciliationCount": result_count}
    await updater(
        db,
        run_id,
        stage=PostApprovalRunStage.CACHE_INVALIDATION,
        message="Invalidating insight cache after reconciliation.",
        output_file_id=str(file_record.id),
        reconciliation_count=result_count,
        stats=result_stats,
    )
    invalidated = await cache_invalidator(
        config.partner,
        source_file.reconciliation_date.strftime("%Y-%m-%d"),
    )
    result.update(
        {
            "stage": "reconciliation",
            "reconciliationCount": result_count,
            "insightCacheInvalidated": invalidated,
        }
    )
    await updater(
        db,
        run_id,
        status=PostApprovalRunStatus.COMPLETED,
        stage=PostApprovalRunStage.CACHE_INVALIDATION,
        message="Post-approval processing completed successfully.",
        finished_at=datetime.now(timezone.utc),
        output_file_id=str(file_record.id),
        reconciliation_count=result_count,
        stats=result_stats,
        errors=ingestion_result.errors,
    )
    await runtime_updater(
        db,
        runtime_run_id,
        status=PartnerRuntimeRunStatus.COMPLETED,
        message="Reconciliation completed successfully.",
        source_file_id=str(file_record.id),
        stats={"resultCount": result_count, **result["stats"]},
        reconciliation_count=result_count,
        finished_at=datetime.now(timezone.utc),
    )
    return result
