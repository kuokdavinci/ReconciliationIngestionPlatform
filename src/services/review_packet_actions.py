"""Shared review packet approval and reprocessing actions."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request

from src.analysis.insights import invalidate_insight_cache
from src.config.cache import ConfigCache
from src.config.loader import ConfigLoader
from src.config.validator import ConfigValidator
from src.core.error_formatting import summarize_runtime_error
from src.core.enums import ProcessingStatus
from src.models.copilot_action import CopilotActionRepository, CopilotActionStatus
from src.models.mapping_config import MappingConfigRepository, MappingConfigStatus
from src.models.post_approval_run import (
    PostApprovalRun,
    PostApprovalRunRepository,
    PostApprovalRunStage,
    PostApprovalRunStatus,
)
from src.models.reconciliation_file import ReconciliationFileRepository
from src.models.data_container import DataContainerRepository
from src.models.reconciliation_result import ReconciliationResultRepository
from src.models.review_packet import (
    ReviewDecisionMode,
    ReviewPacketRepository,
    ReviewPacketStatus,
)
from src.pipeline.ingestion_pipeline import IngestionPipeline
from src.reconciliation.engine import ReconciliationEngine
from src.services.audit import record_audit_event
from src.services.runtime_runs import create_runtime_run, update_runtime_run
from src.models.partner_runtime_run import PartnerRuntimeRunStatus, PartnerRuntimeTriggerType


def _get_db(request: Request):
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available.")
    return db


def _packet_repo(request: Request) -> ReviewPacketRepository:
    return ReviewPacketRepository(_get_db(request))


def build_config_loader(request: Request) -> ConfigLoader:
    db = _get_db(request)
    return build_config_loader_from_db(db)


def build_config_loader_from_db(db) -> ConfigLoader:
    return ConfigLoader(
        MappingConfigRepository(db),
        ConfigCache(),
        ConfigValidator(),
    )


async def sync_action_status(request: Request, action_id: Optional[str], status: str) -> None:
    if not action_id:
        return
    repo = CopilotActionRepository(_get_db(request))
    update = {"status": status, "reviewedAt": datetime.now(timezone.utc)}
    await repo.collection.update_one({"_id": action_id}, {"$set": update})


async def mark_packet(
    request: Request,
    packet_id: str,
    status: ReviewPacketStatus,
    decision_mode: ReviewDecisionMode,
    reviewed_by: Optional[str],
    serializer,
):
    repo = _packet_repo(request)
    packet = await repo.find_one({"_id": packet_id})
    if packet is None:
        raise HTTPException(status_code=404, detail="Review packet not found.")
    if packet.status != ReviewPacketStatus.PENDING:
        raise HTTPException(status_code=400, detail="Only pending review packets can be processed.")

    now = datetime.now(timezone.utc)
    set_fields: dict[str, Any] = {
        "status": status.value,
        "decisionMode": decision_mode.value,
        "reviewedAt": now,
        "reviewedBy": reviewed_by,
    }
    if status == ReviewPacketStatus.APPROVED:
        gates = [dict(g) for g in (packet.validation_gates or [])]
        for g in gates:
            g["status"] = "pass"
        set_fields["validationGates"] = gates
    await repo.collection.update_one(
        {"_id": packet_id},
        {"$set": set_fields},
    )
    await sync_action_status(
        request,
        packet.target_action_id,
        CopilotActionStatus.APPROVED.value
        if status == ReviewPacketStatus.APPROVED
        else CopilotActionStatus.REJECTED.value,
    )
    packet.status = status
    packet.decision_mode = decision_mode
    packet.reviewed_at = now
    packet.reviewed_by = reviewed_by
    audit_date = (
        packet.reconciliation_date.strftime("%Y-%m-%d")
        if getattr(packet, "reconciliation_date", None)
        else None
    )
    await record_audit_event(
        _get_db(request),
        entity_type="REVIEW_PACKET",
        entity_id=packet_id,
        action=decision_mode.value,
        actor=reviewed_by,
        metadata={
            "partner": packet.partner,
            "date": audit_date,
            "status": status.value,
            "reference": packet.draft_mapping_version or packet.draft_mapping_id or packet.source_file_id,
            "draftMappingId": packet.draft_mapping_id,
            "draftMappingVersion": packet.draft_mapping_version,
            "sourceFileId": packet.source_file_id,
        },
    )
    return {"ok": True, "packet": serializer(packet)}


async def update_packet_scope(request: Request, packet_id: str, packet, scope_type: Optional[str]) -> None:
    if not scope_type:
        return
    repo = _packet_repo(request)
    packet.scope_type = scope_type
    await repo.collection.update_one({"_id": packet_id}, {"$set": {"scopeType": scope_type}})
    if packet.source_file_id:
        file_repo = ReconciliationFileRepository(_get_db(request))
        await file_repo.update_one({"_id": packet.source_file_id}, {"scopeType": scope_type})


def serialize_post_approval_run(run: PostApprovalRun) -> dict[str, Any]:
    data = run.model_dump(by_alias=True)
    data["_id"] = str(data["_id"])
    for key in ("createdAt", "updatedAt", "startedAt", "finishedAt"):
        value = data.get(key)
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return data


async def _update_post_approval_run(
    db,
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
    await PostApprovalRunRepository(db).collection.update_one({"_id": run_id}, {"$set": update})


def _track_background_task(app: FastAPI, task: asyncio.Task) -> None:
    tasks = getattr(app.state, "background_tasks", None)
    if tasks is None:
        tasks = set()
        app.state.background_tasks = tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)


async def approve_packet_mapping_and_reprocess(request: Request, packet, reviewed_by: Optional[str]) -> dict | None:
    if not packet.draft_mapping_id:
        return None

    db = _get_db(request)
    mapping_repo = MappingConfigRepository(db)
    config = await mapping_repo.find_one({"_id": packet.draft_mapping_id})
    if config is None or config.status != MappingConfigStatus.PENDING_APPROVAL:
        return None

    now = datetime.now(timezone.utc)
    current_approved = await mapping_repo.find_by_partner_and_type(
        config.partner, config.workflow_type, config.file_type
    )
    if current_approved is not None:
        await mapping_repo.collection.update_one(
            {"_id": str(current_approved.id)},
            {"$set": {
                "status": MappingConfigStatus.SUPERSEDED.value,
                "supersededAt": now,
                "supersededByConfigId": str(config.id),
            }},
        )
    health = dict(config.config_health or {})
    health.update(
        {
            "stale": False,
            "status": MappingConfigStatus.APPROVED.value,
            "approvedAt": now,
            "reasoning": (health.get("reasoning") or "Approved from review packet."),
        }
    )
    await mapping_repo.collection.update_one(
        {"_id": packet.draft_mapping_id},
        {"$set": {
            "status": MappingConfigStatus.APPROVED.value,
            "approvedAt": now,
            "approvedBy": reviewed_by,
            "configHealth": health,
        }},
    )
    config.status = MappingConfigStatus.APPROVED
    config.approved_at = now
    config.approved_by = reviewed_by
    config.config_health = health

    run = PostApprovalRun(
        packetId=str(packet.id),
        partner=packet.partner,
        date=packet.reconciliation_date.strftime("%Y-%m-%d") if getattr(packet, "reconciliation_date", None) else None,
        status=PostApprovalRunStatus.QUEUED,
        stage=PostApprovalRunStage.APPROVAL,
        message="Approved. Post-approval processing is queued.",
        sourceFileId=getattr(packet, "source_file_id", None),
    )
    run_repo = PostApprovalRunRepository(db)
    await run_repo.create(run)
    task = asyncio.create_task(
        _run_post_approval_reprocess(
            request.app,
            str(run.id),
            str(packet.id),
            str(config.id),
        )
    )
    _track_background_task(request.app, task)
    return serialize_post_approval_run(run)


async def _run_post_approval_reprocess(app: FastAPI, run_id: str, packet_id: str, config_id: str) -> None:
    db = getattr(app.state, "db", None)
    if db is None:
        return
    packet_repo = ReviewPacketRepository(db)
    mapping_repo = MappingConfigRepository(db)
    packet = await packet_repo.find_one({"_id": packet_id})
    config = await mapping_repo.find_one({"_id": config_id})
    if packet is None or config is None:
        await _update_post_approval_run(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.APPROVAL,
            message="Packet or approved mapping could not be loaded for post-approval processing.",
            finished_at=datetime.now(timezone.utc),
        )
        return
    try:
        await reprocess_and_reconcile(db, packet, config, run_id)
    except Exception as exc:
        summarized_error = summarize_runtime_error(exc)
        await _update_post_approval_run(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            message=f"Post-approval processing failed: {summarized_error}",
            finished_at=datetime.now(timezone.utc),
            errors=[summarized_error],
        )


async def reprocess_and_reconcile(db, packet, config, run_id: str) -> dict | None:
    runtime_run = await create_runtime_run(
        db,
        partner=config.partner,
        date=packet.reconciliation_date.strftime("%Y-%m-%d"),
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
    if not source_file_path or not source_file_id:
        await update_runtime_run(
            db,
            runtime_run_id,
            status=PartnerRuntimeRunStatus.FAILED,
            message="Review packet has no source file attached for post-approval processing.",
            finished_at=datetime.now(timezone.utc),
        )
        await _update_post_approval_run(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.APPROVAL,
            message="Review packet has no source file attached for post-approval processing.",
            finished_at=datetime.now(timezone.utc),
        )
        return None

    path = Path(source_file_path)
    if not path.exists():
        await update_runtime_run(
            db,
            runtime_run_id,
            status=PartnerRuntimeRunStatus.FAILED,
            message=f"Source file is no longer available at {source_file_path}.",
            finished_at=datetime.now(timezone.utc),
        )
        await _update_post_approval_run(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.APPROVAL,
            message=f"Source file is no longer available at {source_file_path}.",
            finished_at=datetime.now(timezone.utc),
        )
        return None

    file_repo = ReconciliationFileRepository(db)
    source_file = await file_repo.find_one({"_id": source_file_id})
    if source_file is None:
        await update_runtime_run(
            db,
            runtime_run_id,
            status=PartnerRuntimeRunStatus.FAILED,
            message=f"Source file record {source_file_id} was not found.",
            finished_at=datetime.now(timezone.utc),
        )
        await _update_post_approval_run(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.APPROVAL,
            message=f"Source file record {source_file_id} was not found.",
            finished_at=datetime.now(timezone.utc),
        )
        return None

    # PostgreSQL is the canonical transaction store.
    await DataContainerRepository(db).delete_by_source_file(source_file_id)
    date_str = source_file.reconciliation_date.strftime("%Y-%m-%d")
    await ReconciliationResultRepository(db).delete_by_partner_and_date(
        config.partner,
        date_str,
    )
    
    if source_file.processing_status != ProcessingStatus.COMPLETED:
        await file_repo.delete_one({"_id": source_file_id})

    await _update_post_approval_run(
        db,
        run_id,
        status=PostApprovalRunStatus.INGESTING,
        stage=PostApprovalRunStage.INGESTION,
        message="Ingesting partner file with the approved mapping.",
        started_at=datetime.now(timezone.utc),
    )
    await update_runtime_run(
        db,
        runtime_run_id,
        status=PartnerRuntimeRunStatus.INGESTING,
        message="Ingesting partner file with the approved mapping.",
        started_at=datetime.now(timezone.utc),
    )

    from src.config.settings import settings
    pipeline = IngestionPipeline(
        db=db,
        config_loader=build_config_loader_from_db(db),
        batch_size=settings.ingest_batch_size,
        logger=None,
        fast_mode=True,
    )
    ingestion_result = await pipeline.process_file(
        file_path=source_file_path,
        partner=config.partner,
        workflow_type=config.workflow_type,
        file_type=config.file_type,
        reconciliation_date=source_file.reconciliation_date,
        config_version=config.config_version,
        # Guided Review reprocessing is a new delivery attempt, but it does
        # not come through the fetcher. Supply a deterministic fetch-unit
        # identity so the unique Mongo index never receives null.
        fetch_unit_metadata={
            "sourceEndpoint": f"review://{source_file_id}",
            "cursor": f"post-approval:{run_id}",
            "windowStart": source_file.reconciliation_date.isoformat(),
            "windowEnd": source_file.reconciliation_date.isoformat(),
        },
        enable_config_health_check=False,
    )
    processing_status = getattr(
        ingestion_result.file_record.processing_status,
        "value",
        ingestion_result.file_record.processing_status,
    )
    result = {
        "ok": processing_status == ProcessingStatus.COMPLETED.value,
        "stage": "ingestion",
        "partner": config.partner,
        "date": source_file.reconciliation_date.strftime("%Y-%m-%d"),
        "processingStatus": processing_status,
        "fileId": str(ingestion_result.file_record.id),
        "stats": {
            "totalRows": ingestion_result.stats.total_rows,
            "successRows": ingestion_result.stats.success_rows,
            "duplicateRows": ingestion_result.stats.duplicate_rows,
            "failedRows": ingestion_result.stats.failed_rows,
        },
        "errors": ingestion_result.errors,
    }
    if processing_status != ProcessingStatus.COMPLETED.value:
        await update_runtime_run(
            db,
            runtime_run_id,
            status=PartnerRuntimeRunStatus.FAILED,
            message="Ingestion failed after approval.",
            source_file_id=str(ingestion_result.file_record.id),
            stats=result["stats"],
            finished_at=datetime.now(timezone.utc),
        )
        await _update_post_approval_run(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.INGESTION,
            message="Ingestion failed after approval.",
            finished_at=datetime.now(timezone.utc),
            output_file_id=str(ingestion_result.file_record.id),
            stats=result["stats"],
            errors=ingestion_result.errors,
        )
        return result

    if packet.scope_type:
        await file_repo.update_one(
            {"_id": str(ingestion_result.file_record.id)},
            {"scopeType": packet.scope_type},
        )

    await _update_post_approval_run(
        db,
        run_id,
        status=PostApprovalRunStatus.RECONCILING,
        stage=PostApprovalRunStage.RECONCILIATION,
        message="Reconciling ingested partner rows against internal transactions.",
        output_file_id=str(ingestion_result.file_record.id),
        stats=result["stats"],
        errors=ingestion_result.errors,
    )
    await update_runtime_run(
        db,
        runtime_run_id,
        status=PartnerRuntimeRunStatus.RECONCILING,
        message="Reconciling ingested partner rows against internal transactions.",
        source_file_id=str(ingestion_result.file_record.id),
        stats=result["stats"],
    )

    recon_date = source_file.reconciliation_date
    recon_results = await ReconciliationEngine(db, fast_mode=True).reconcile(
        config.partner,
        recon_date,
        source_file_id=str(ingestion_result.file_record.id),
        reconciliation_run_id=runtime_run_id,
        mapping_version=getattr(config, "config_version", None) or str(config.id),
    )

    await _update_post_approval_run(
        db,
        run_id,
        stage=PostApprovalRunStage.CACHE_INVALIDATION,
        message="Invalidating insight cache after reconciliation.",
        output_file_id=str(ingestion_result.file_record.id),
        reconciliation_count=len(recon_results),
        stats={**result["stats"], "resultCount": len(recon_results), "reconciliationCount": len(recon_results)},
    )

    invalidated = await invalidate_insight_cache(
        config.partner,
        recon_date.strftime("%Y-%m-%d"),
    )
    result.update(
        {
            "stage": "reconciliation",
            "reconciliationCount": len(recon_results),
            "insightCacheInvalidated": invalidated,
        }
    )
    await _update_post_approval_run(
        db,
        run_id,
        status=PostApprovalRunStatus.COMPLETED,
        stage=PostApprovalRunStage.CACHE_INVALIDATION,
        message="Post-approval processing completed successfully.",
        finished_at=datetime.now(timezone.utc),
        output_file_id=str(ingestion_result.file_record.id),
        reconciliation_count=len(recon_results),
        stats={**result["stats"], "resultCount": len(recon_results), "reconciliationCount": len(recon_results)},
        errors=ingestion_result.errors,
    )
    await update_runtime_run(
        db,
        runtime_run_id,
        status=PartnerRuntimeRunStatus.COMPLETED,
        message="Reconciliation completed successfully.",
        source_file_id=str(ingestion_result.file_record.id),
        stats={"resultCount": len(recon_results), **result["stats"]},
        reconciliation_count=len(recon_results),
        finished_at=datetime.now(timezone.utc),
    )
    return result
