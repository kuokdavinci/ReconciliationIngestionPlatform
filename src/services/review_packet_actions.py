"""Shared review packet approval and reprocessing actions."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, Request

from src.analysis.insights import invalidate_insight_cache
from src.config.cache import ConfigCache
from src.config.loader import ConfigLoader
from src.config.validator import ConfigValidator
from src.core.enums import ProcessingStatus
from src.models.copilot_action import CopilotActionRepository, CopilotActionStatus
from src.models.mapping_config import MappingConfigRepository, MappingConfigStatus
from src.models.reconciliation_file import ReconciliationFileRepository
from src.models.review_packet import (
    ReviewDecisionMode,
    ReviewPacketRepository,
    ReviewPacketStatus,
)
from src.pipeline.ingestion_pipeline import IngestionPipeline
from src.reconciliation.engine import ReconciliationEngine


def _get_db(request: Request):
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available.")
    return db


def _packet_repo(request: Request) -> ReviewPacketRepository:
    return ReviewPacketRepository(_get_db(request))


def build_config_loader(request: Request) -> ConfigLoader:
    db = _get_db(request)
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
    await repo.collection.update_one(
        {"_id": packet_id},
        {"$set": {
            "status": status.value,
            "decisionMode": decision_mode.value,
            "reviewedAt": now,
            "reviewedBy": reviewed_by,
        }},
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


async def approve_packet_mapping_and_reprocess(request: Request, packet, reviewed_by: Optional[str]) -> dict | None:
    if not packet.draft_mapping_id:
        return None

    mapping_repo = MappingConfigRepository(_get_db(request))
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
    return await reprocess_and_reconcile(request, packet, config)


async def reprocess_and_reconcile(request: Request, packet, config) -> dict | None:
    source_file_path = getattr(packet, "source_file_path", None)
    source_file_id = getattr(packet, "source_file_id", None)
    if not source_file_path or not source_file_id:
        return None

    path = Path(source_file_path)
    if not path.exists():
        return {
            "ok": False,
            "stage": "reprocess",
            "reason": f"Source file is no longer available at {source_file_path}.",
        }

    db = _get_db(request)
    file_repo = ReconciliationFileRepository(db)
    source_file = await file_repo.find_one({"_id": source_file_id})
    if source_file is None:
        return {
            "ok": False,
            "stage": "reprocess",
            "reason": f"Source file record {source_file_id} was not found.",
        }

    if source_file.processing_status == ProcessingStatus.FAILED:
        await db["data_container"].delete_many({"sourceFileId": source_file_id})
        await file_repo.delete_one({"_id": source_file_id})

    pipeline = IngestionPipeline(
        db=db,
        config_loader=build_config_loader(request),
        batch_size=100,
        logger=None,
    )
    ingestion_result = await pipeline.process_file(
        file_path=source_file_path,
        partner=config.partner,
        workflow_type=config.workflow_type,
        file_type=config.file_type,
        reconciliation_date=source_file.reconciliation_date,
        config_version=config.config_version,
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
            "failedRows": ingestion_result.stats.failed_rows,
        },
        "errors": ingestion_result.errors,
    }
    if processing_status != ProcessingStatus.COMPLETED.value:
        return result

    if packet.scope_type:
        await file_repo.update_one(
            {"_id": str(ingestion_result.file_record.id)},
            {"scopeType": packet.scope_type},
        )

    recon_date = source_file.reconciliation_date
    recon_results = await ReconciliationEngine(db).reconcile(
        config.partner,
        recon_date,
        source_file_id=str(ingestion_result.file_record.id),
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
    return result
