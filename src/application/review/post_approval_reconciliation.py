"""Post-approval run lifecycle and file-level reconciliation service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
import inspect
from typing import Any, Optional

from src.analysis.insights import invalidate_insight_cache
from src.application.review.raw_stream import resolve_review_source_file
from src.application.runtime.service import create_runtime_run, update_runtime_run
from src.config.settings import settings
from src.core.utils import business_date, summarize_runtime_error
from src.core.enums import ProcessingStatus, ReconciliationScopeType
from src.domain.ingestion.quarantine import QuarantineQuery
from src.domain.review.models import (
    PostApprovalRun,
    PostApprovalRunStage,
    PostApprovalQualityGateStatus,
    PostApprovalRunStatus,
)
from src.domain.runtime.models import PartnerRuntimeRunStatus, PartnerRuntimeTriggerType
from src.infrastructure.ingestion.composition import build_ingestion_pipeline
from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository
from src.infrastructure.ingestion.quarantine_repository import IngestionQuarantineRepository
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
from src.infrastructure.runtime.repository import PartnerRuntimeRunRepository
from pymongo import ReturnDocument


ScheduleBackground = Callable[[Awaitable[None]], None]


def _batch_fatal_quality_summary(ingestion_result: Any) -> dict[str, Any] | None:
    """Build a bounded batch-fatal projection from the ingestion result."""
    quality_decision = getattr(ingestion_result, "quality_decision", None)
    quality_decision = getattr(quality_decision, "value", quality_decision)
    quality_summary = getattr(ingestion_result, "quality_summary", None)
    outcome_counts = getattr(quality_summary, "outcome_counts", {}) or {}
    has_batch_fatal = quality_decision == "FAIL" or bool(
        outcome_counts.get("BATCH_FATAL", 0)
    )
    if not has_batch_fatal:
        return None

    stats = getattr(ingestion_result, "stats", None)
    top_rule_codes = getattr(quality_summary, "top_rule_codes", []) or []
    return {
        "outcome": "BATCH_FATAL",
        "errorCodes": [str(code) for code in top_rule_codes[:10]],
        "totalRows": int(getattr(stats, "total_rows", 0) or 0),
        "failedRows": int(getattr(stats, "failed_rows", 0) or 0),
        "activeRows": 0,
    }


async def _quarantine_quality_gate(
    db: Any,
    *,
    packet_id: str,
    run_id: str,
    source_file_id: str | None,
) -> tuple[PostApprovalQualityGateStatus, dict[str, int]]:
    """Project bounded quarantine counts into the post-approval quality gate."""
    repository = IngestionQuarantineRepository(db)
    try:
        summary = await repository.summarize(
            # New rows are correlated to the post-approval run. The source-file
            # fallback keeps older quarantine documents visible after deployment.
            QuarantineQuery(postApprovalRunId=run_id, limit=200)
        )
        if summary.get("total", 0) == 0 and source_file_id:
            summary = await repository.summarize(
                QuarantineQuery(sourceFileId=source_file_id, limit=200)
            )
    except (AttributeError, TypeError):
        # Compatibility doubles and legacy adapters without async Mongo
        # counters cannot project a gate; the ingestion result remains the
        # source of truth in those environments.
        return PostApprovalQualityGateStatus.PASS, {}
    bounded = {
        "totalRows": int(summary.get("total", 0) or 0),
        "pendingRows": int(summary.get("pending", 0) or 0),
        "reprocessingRows": int(summary.get("reprocessing", 0) or 0),
        "resolvedRows": int(summary.get("resolved", 0) or 0),
        "rejectedRows": int(summary.get("rejected", 0) or 0),
        "overdueRows": int(summary.get("overdue", 0) or 0),
        "highPriorityRows": int(summary.get("highPriority", 0) or 0),
    }
    bounded["activeRows"] = bounded["pendingRows"] + bounded["reprocessingRows"]
    status = (
        PostApprovalQualityGateStatus.REVIEW_REQUIRED
        if bounded["activeRows"] > 0
        else PostApprovalQualityGateStatus.PASS
    )
    return status, bounded


async def _persist_packet_quality_gate(
    db: Any,
    packet: Any,
    run_id: str,
    status: PostApprovalQualityGateStatus,
    summary: dict[str, Any],
) -> None:
    """Keep the packet as the operator-facing parent of the review batch."""
    packet.quality_gate_status = status
    packet.quality_gate_summary = summary
    packet.post_approval_run_id = run_id
    result = ReviewPacketRepository(db).collection.update_one(
        {"_id": str(packet.id)},
        {
            "$set": {
                "qualityGateStatus": status.value,
                "qualityGateSummary": summary,
                "postApprovalRunId": run_id,
            }
        },
    )
    if inspect.isawaitable(result):
        await result


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
    quality_gate_status: Optional[PostApprovalQualityGateStatus] = None,
    quality_gate_summary: Optional[dict[str, Any]] = None,
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
    if quality_gate_status is not None:
        update["qualityGateStatus"] = quality_gate_status.value
    if quality_gate_summary is not None:
        update["qualityGateSummary"] = quality_gate_summary
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
    packet_update = ReviewPacketRepository(db).collection.update_one(
        {"_id": str(packet.id)},
        {"$set": {"postApprovalRunId": str(run.id)}},
    )
    if inspect.isawaitable(packet_update):
        await packet_update
    if run_task is None:
        run_task = run_post_approval_reprocess
    schedule_background(run_task(db, str(run.id), str(packet.id), str(config.id)))
    return serialize_post_approval_run(run)


async def _mark_latest_post_approval_runtime_failed(
    db: Any,
    partner: str,
    message: str,
    *,
    runtime_repository_factory: Callable[[Any], Any] = PartnerRuntimeRunRepository,
    runtime_updater: Callable[..., Awaitable[None]] = update_runtime_run,
) -> None:
    """Close the runtime projection when the post-approval worker crashes.

    The post-approval record and the shared runtime record are separate
    projections. The worker must close both, otherwise the schedules view
    keeps treating the latest ``INGESTING``/``RECONCILING`` runtime as active
    forever after an unexpected exception.
    """
    runtime_run = await runtime_repository_factory(db).find_latest_by_partner(partner)
    if runtime_run is None:
        return
    trigger_type = getattr(runtime_run.trigger_type, "value", runtime_run.trigger_type)
    if trigger_type != PartnerRuntimeTriggerType.POST_APPROVAL_REPROCESS.value:
        return
    status = getattr(runtime_run.status, "value", runtime_run.status)
    if status in {
        PartnerRuntimeRunStatus.COMPLETED.value,
        PartnerRuntimeRunStatus.FAILED.value,
    }:
        return
    await runtime_updater(
        db,
        str(runtime_run.id),
        status=PartnerRuntimeRunStatus.FAILED,
        message=f"Post-approval processing failed: {message}",
        stats={
            "errorCode": "POST_APPROVAL_PROCESSING_FAILED",
            "error": message,
            "retryable": False,
        },
        finished_at=datetime.now(timezone.utc),
    )


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
    runtime_repository_factory: Callable[[Any], Any] = PartnerRuntimeRunRepository,
    runtime_updater: Callable[..., Awaitable[None]] = update_runtime_run,
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
        await _mark_latest_post_approval_runtime_failed(
            db,
            packet.partner,
            summarized_error,
            runtime_repository_factory=runtime_repository_factory,
            runtime_updater=runtime_updater,
        )


async def continue_waiting_post_approval_run(
    db: Any,
    run_id: str,
    *,
    packet_repository_factory: Callable[[Any], Any] = ReviewPacketRepository,
    config_repository_factory: Callable[[Any], Any] = MappingConfigRepository,
    run_repository_factory: Callable[[Any], Any] = PostApprovalRunRepository,
    runtime_repository_factory: Callable[[Any], Any] = PartnerRuntimeRunRepository,
    file_repository_factory: Callable[[Any], Any] = ReconciliationFileRepository,
    reconciliation_service_builder: Callable[..., Any] = build_reconciliation_service,
    cache_invalidator: Callable[[str, str], Awaitable[Any]] = invalidate_insight_cache,
) -> dict[str, Any] | None:
    """Continue reconciliation once a packet's active quarantine is empty."""
    run_repository = run_repository_factory(db)
    raw = await run_repository.collection.find_one_and_update(
        {"_id": run_id, "status": PostApprovalRunStatus.WAITING_REVIEW.value},
        {
            "$set": {
                "status": PostApprovalRunStatus.RECONCILING.value,
                "stage": PostApprovalRunStage.RECONCILIATION.value,
                "message": "Quarantine review completed. Reconciliation is continuing.",
                "updatedAt": datetime.now(timezone.utc),
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if raw is None:
        return None
    run = run_repository._from_mongo(raw)
    packet = await packet_repository_factory(db).find_one({"_id": run.packet_id})
    config = None
    if packet is not None:
        config_id = packet.draft_mapping_id or packet.active_runtime_config_id
        if config_id:
            config = await config_repository_factory(db).find_one({"_id": config_id})
    source_file_id = run.output_file_id or run.source_file_id
    if packet is None or config is None or source_file_id is None:
        await update_post_approval_run(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.RECONCILIATION,
            message="Post-approval continuation could not load its packet, mapping, or output file.",
            finished_at=datetime.now(timezone.utc),
        )
        return {"ok": False, "outcome": "CONTINUATION_UNAVAILABLE"}

    quality_gate_status, quality_gate_summary = await _quarantine_quality_gate(
        db,
        packet_id=str(packet.id),
        run_id=run_id,
        source_file_id=source_file_id,
    )
    if quality_gate_summary.get("activeRows", 0) > 0:
        await _persist_packet_quality_gate(
            db,
            packet,
            run_id,
            quality_gate_status,
            quality_gate_summary,
        )
        await update_post_approval_run(
            db,
            run_id,
            status=PostApprovalRunStatus.WAITING_REVIEW,
            stage=PostApprovalRunStage.INGESTION,
            message="Additional quarantine records still require review.",
            quality_gate_status=quality_gate_status,
            quality_gate_summary=quality_gate_summary,
        )
        return {
            "ok": False,
            "outcome": "WAITING_REVIEW",
            "qualityGateStatus": quality_gate_status.value,
            "qualityGateSummary": quality_gate_summary,
        }

    source_file = await file_repository_factory(db).find_one({"_id": source_file_id})
    if source_file is None:
        await update_post_approval_run(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.RECONCILIATION,
            message="Post-approval continuation could not find its output file.",
            finished_at=datetime.now(timezone.utc),
        )
        return {"ok": False, "outcome": "CONTINUATION_UNAVAILABLE"}

    await _persist_packet_quality_gate(
        db,
        packet,
        run_id,
        PostApprovalQualityGateStatus.PASS,
        quality_gate_summary,
    )
    date_value = source_file.reconciliation_date
    runtime = await runtime_repository_factory(db).collection.find_one(
        {
            "triggerType": PartnerRuntimeTriggerType.POST_APPROVAL_REPROCESS.value,
            "sourceFileId": source_file_id,
        },
        sort=[("createdAt", -1)],
    )
    runtime_id = str(runtime["_id"]) if runtime is not None else None
    try:
        results = await reconciliation_service_builder(db).reconcile(
            config.partner,
            date_value,
            source_file_id=source_file_id,
            reconciliation_run_id=runtime_id,
            mapping_version=getattr(config, "config_version", None) or str(config.id),
        )
        result_count = len(results)
        await update_post_approval_run(
            db,
            run_id,
            status=PostApprovalRunStatus.COMPLETED,
            stage=PostApprovalRunStage.RECONCILIATION,
            message="Quarantine review completed and reconciliation finished.",
            finished_at=datetime.now(timezone.utc),
            output_file_id=source_file_id,
            reconciliation_count=result_count,
            stats={
                **run.stats,
                "resultCount": result_count,
                "reconciliationCount": result_count,
                "qualityGate": quality_gate_summary,
            },
            quality_gate_status=PostApprovalQualityGateStatus.PASS,
            quality_gate_summary=quality_gate_summary,
        )
        if runtime_id:
            await update_runtime_run(
                db,
                runtime_id,
                status=PartnerRuntimeRunStatus.COMPLETED,
                message="Reconciliation completed after quarantine review.",
                source_file_id=source_file_id,
                reconciliation_count=result_count,
                stats={"resultCount": result_count, "qualityGate": quality_gate_summary},
                finished_at=datetime.now(timezone.utc),
            )
        await cache_invalidator(config.partner, date_value.strftime("%Y-%m-%d"))
        return {
            "ok": True,
            "outcome": "RECONCILED_AFTER_QUARANTINE",
            "reconciliationCount": result_count,
            "qualityGateStatus": PostApprovalQualityGateStatus.PASS.value,
            "qualityGateSummary": quality_gate_summary,
        }
    except Exception as exc:
        message = summarize_runtime_error(exc)
        await update_post_approval_run(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.RECONCILIATION,
            message="Reconciliation failed after quarantine review.",
            finished_at=datetime.now(timezone.utc),
            errors=[{"errorCode": "RECONCILIATION_FAILED", "reason": message}],
        )
        return {"ok": False, "outcome": "RECONCILIATION_FAILED"}


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
            "reviewPacketId": str(packet.id),
            "postApprovalRunId": run_id,
            "sourceUnitKey": getattr(source_file, "fetch_unit_key", None),
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
            "qualityCounters": dict(getattr(ingestion_result, "quality_counters", {}) or {}),
        },
        "errors": ingestion_result.errors,
    }
    batch_fatal_summary = _batch_fatal_quality_summary(ingestion_result)
    if processing_status != ProcessingStatus.COMPLETED.value:
        if batch_fatal_summary is not None:
            quality_gate_status = PostApprovalQualityGateStatus.FAIL
            result["qualityGateStatus"] = quality_gate_status.value
            result["qualityGateSummary"] = batch_fatal_summary
            await _persist_packet_quality_gate(
                db, packet, run_id, quality_gate_status, batch_fatal_summary
            )
            failure_stats = {**result["stats"], "qualityGate": batch_fatal_summary}
            await runtime_updater(
                db,
                runtime_run_id,
                status=PartnerRuntimeRunStatus.FAILED,
                message="Post-approval quality gate failed before reconciliation.",
                source_file_id=str(file_record.id),
                stats=failure_stats,
                finished_at=datetime.now(timezone.utc),
            )
            await updater(
                db,
                run_id,
                status=PostApprovalRunStatus.FAILED,
                stage=PostApprovalRunStage.INGESTION,
                message="Post-approval quality gate failed before reconciliation.",
                finished_at=datetime.now(timezone.utc),
                output_file_id=str(file_record.id),
                stats=failure_stats,
                errors=ingestion_result.errors,
                quality_gate_status=quality_gate_status,
                quality_gate_summary=batch_fatal_summary,
            )
            return result
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

    if batch_fatal_summary is not None:
        quality_gate_status = PostApprovalQualityGateStatus.FAIL
        quality_gate_summary = batch_fatal_summary
        await _persist_packet_quality_gate(
            db, packet, run_id, quality_gate_status, quality_gate_summary
        )
        await runtime_updater(
            db,
            runtime_run_id,
            status=PartnerRuntimeRunStatus.FAILED,
            message="Post-approval quality gate failed before reconciliation.",
            source_file_id=str(file_record.id),
            stats={**result["stats"], "qualityGate": quality_gate_summary},
            finished_at=datetime.now(timezone.utc),
        )
        await updater(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.INGESTION,
            message="Post-approval quality gate failed before reconciliation.",
            finished_at=datetime.now(timezone.utc),
            output_file_id=str(file_record.id),
            stats={**result["stats"], "qualityGate": quality_gate_summary},
            errors=ingestion_result.errors,
            quality_gate_status=quality_gate_status,
            quality_gate_summary=quality_gate_summary,
        )
        result["qualityGateStatus"] = quality_gate_status.value
        result["qualityGateSummary"] = quality_gate_summary
        return result

    quality_gate_status, quality_gate_summary = await _quarantine_quality_gate(
        db,
        packet_id=str(packet.id),
        run_id=run_id,
        source_file_id=str(file_record.id),
    )
    result["qualityGateStatus"] = quality_gate_status.value
    result["qualityGateSummary"] = quality_gate_summary
    result["stats"] = {
        **result["stats"],
        "qualityGate": quality_gate_summary,
    }
    await _persist_packet_quality_gate(
        db, packet, run_id, quality_gate_status, quality_gate_summary
    )
    if quality_gate_status is PostApprovalQualityGateStatus.REVIEW_REQUIRED:
        active_rows = quality_gate_summary["activeRows"]
        message = f"{active_rows} quarantine record(s) require review before reconciliation."
        await updater(
            db,
            run_id,
            status=PostApprovalRunStatus.WAITING_REVIEW,
            stage=PostApprovalRunStage.INGESTION,
            message=message,
            output_file_id=str(file_record.id),
            stats=result["stats"],
            errors=ingestion_result.errors,
            quality_gate_status=quality_gate_status,
            quality_gate_summary=quality_gate_summary,
        )
        await runtime_updater(
            db,
            runtime_run_id,
            status=PartnerRuntimeRunStatus.WAITING_REVIEW,
            message=message,
            source_file_id=str(file_record.id),
            stats=result["stats"],
        )
        result.update({"ok": False, "waitingForReview": True, "stage": "ingestion"})
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
        quality_gate_status=quality_gate_status,
        quality_gate_summary=quality_gate_summary,
    )
    await runtime_updater(
        db,
        runtime_run_id,
        status=PartnerRuntimeRunStatus.RECONCILING,
        message="Reconciling ingested partner rows against internal transactions.",
        source_file_id=str(file_record.id),
        stats=result["stats"],
    )
    recon_results = await reconciliation_service_builder(db).reconcile(
        config.partner,
        source_file.reconciliation_date,
        source_file_id=str(file_record.id),
        reconciliation_run_id=runtime_run_id,
        mapping_version=getattr(config, "config_version", None) or str(config.id),
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
        quality_gate_status=quality_gate_status,
        quality_gate_summary=quality_gate_summary,
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
