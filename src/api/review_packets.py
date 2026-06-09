"""Approval desk review packet endpoints."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

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
from src.normalizer.normalizer import TransactionNormalizer
from src.pipeline.ingestion_pipeline import IngestionPipeline
from src.readers import create_reader
from src.reconciliation.engine import ReconciliationEngine

router = APIRouter(prefix="/api/v1/review-packets")


def _get_db(request: Request):
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available.")
    return db


def _repo(request: Request) -> ReviewPacketRepository:
    return ReviewPacketRepository(_get_db(request))


def _config_loader(request: Request) -> ConfigLoader:
    db = _get_db(request)
    return ConfigLoader(
        MappingConfigRepository(db),
        ConfigCache(),
        ConfigValidator(),
    )


def _serialize(packet) -> dict:
    data = packet.model_dump(by_alias=True)
    data["_id"] = str(data["_id"])
    data["reviewItemId"] = data["_id"]
    return data


class ReviewDecisionPayload(BaseModel):
    reviewed_by: Optional[str] = None
    scope_type: Optional[str] = Field(default=None, alias="scopeType")


def _upsert_validation_gate(packet, gate: dict) -> list[dict]:
    gates = [dict(item) for item in (packet.validation_gates or []) if item.get("gateKey") != gate["gateKey"]]
    gates.append(gate)
    return gates


def _has_passing_runtime_gate(packet) -> bool:
    for gate in packet.validation_gates or []:
        if gate.get("gateKey") == "runtime_validation":
            return str(gate.get("status", "")).lower() == "pass"
    return False


async def _sync_action_status(request: Request, action_id: Optional[str], status: str) -> None:
    if not action_id:
        return
    repo = CopilotActionRepository(_get_db(request))
    update = {"status": status, "reviewedAt": datetime.now(timezone.utc)}
    await repo.collection.update_one({"_id": action_id}, {"$set": update})


@router.get("")
async def list_review_packets(
    request: Request,
    status: Optional[str] = Query(default=None),
    partner: Optional[str] = Query(default=None),
):
    query: dict = {}
    if status:
        query["status"] = status
    if partner:
        query["partner"] = partner
    packets = await _repo(request).find_many(query)
    packets.sort(key=lambda item: item.created_at, reverse=True)
    return {"packets": [_serialize(packet) for packet in packets]}


@router.get("/{packet_id}")
async def get_review_packet(request: Request, packet_id: str):
    packet = await _repo(request).find_one({"_id": packet_id})
    if packet is None:
        raise HTTPException(status_code=404, detail="Review packet not found.")
    return {"packet": _serialize(packet)}


async def _mark_packet(
    request: Request,
    packet_id: str,
    status: ReviewPacketStatus,
    decision_mode: ReviewDecisionMode,
    reviewed_by: Optional[str],
):
    repo = _repo(request)
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
    await _sync_action_status(
        request,
        packet.target_action_id,
        CopilotActionStatus.APPROVED.value if status == ReviewPacketStatus.APPROVED else CopilotActionStatus.REJECTED.value,
    )
    packet.status = status
    packet.decision_mode = decision_mode
    packet.reviewed_at = now
    packet.reviewed_by = reviewed_by
    return {"ok": True, "packet": _serialize(packet)}


async def _reprocess_and_reconcile(request: Request, packet, config) -> dict | None:
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
        config_loader=_config_loader(request),
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
            {"scopeType": packet.scope_type}
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
    result.update({
        "stage": "reconciliation",
        "reconciliationCount": len(recon_results),
        "insightCacheInvalidated": invalidated,
    })
    return result


async def _run_runtime_validation(request: Request, packet, config) -> dict:
    source_file_path = getattr(packet, "source_file_path", None)
    if not source_file_path:
        return {
            "gateKey": "runtime_validation",
            "label": "Runtime validation",
            "status": "fail",
            "reason": "No source file path is attached to this review packet.",
            "details": {"successRows": 0, "failedRows": 0, "sampledRows": 0},
        }

    path = Path(source_file_path)
    if not path.exists():
        return {
            "gateKey": "runtime_validation",
            "label": "Runtime validation",
            "status": "fail",
            "reason": f"Source file is not available at {source_file_path}.",
            "details": {"successRows": 0, "failedRows": 0, "sampledRows": 0},
        }

    sampled_rows = 0
    success_rows = 0
    failed_rows = 0
    failed_examples: list[dict] = []

    with create_reader(source_file_path, config) as reader:
        normalizer = TransactionNormalizer(config.field_mappings)
        for row in reader.iter_rows():
            sampled_rows += 1
            row_number = config.start_row + sampled_rows - 1
            norm_result = normalizer.normalize(row, row_number)
            if norm_result.errors:
                failed_rows += 1
                failed_examples.append({
                    "row": row_number,
                    "reason": norm_result.errors[0].reason,
                    "field": norm_result.errors[0].field,
                })
            else:
                txn, build_errors = TransactionNormalizer.build_canonical(
                    norm_result.data, [], row_number
                )
                if txn is None:
                    failed_rows += 1
                    failed_examples.append({
                        "row": row_number,
                        "reason": build_errors[0].reason,
                        "field": build_errors[0].field,
                    })
                else:
                    success_rows += 1
            if sampled_rows >= 20:
                break

    if sampled_rows == 0:
        status = "fail"
        reason = "No readable data rows were produced by the proposed mapping."
    elif success_rows == 0:
        status = "fail"
        reason = "The proposed mapping could not normalize any sampled rows."
    elif failed_rows == 0:
        status = "pass"
        reason = f"Validated successfully on {success_rows}/{sampled_rows} sampled rows."
    else:
        success_rate = success_rows / sampled_rows
        status = "pass" if success_rate >= 0.8 else "fail"
        reason = (
            f"Validated {success_rows}/{sampled_rows} sampled rows successfully."
            if status == "pass"
            else f"Only {success_rows}/{sampled_rows} sampled rows normalized successfully."
        )

    gate = {
        "gateKey": "runtime_validation",
        "label": "Runtime validation",
        "status": status,
        "reason": reason,
        "details": {
            "sampledRows": sampled_rows,
            "successRows": success_rows,
            "failedRows": failed_rows,
            "failedExamples": failed_examples[:3],
        },
    }
    await _repo(request).collection.update_one(
        {"_id": str(packet.id)},
        {"$set": {"validationGates": _upsert_validation_gate(packet, gate)}},
    )
    return gate


@router.post("/{packet_id}/validate-runtime")
async def validate_runtime_packet(request: Request, packet_id: str):
    repo = _repo(request)
    packet = await repo.find_one({"_id": packet_id})
    if packet is None:
        raise HTTPException(status_code=404, detail="Review packet not found.")
    if not packet.draft_mapping_id:
        raise HTTPException(status_code=400, detail="Review item has no draft mapping.")

    mapping_repo = MappingConfigRepository(_get_db(request))
    config = await mapping_repo.find_one({"_id": packet.draft_mapping_id})
    if config is None:
        raise HTTPException(status_code=404, detail="Draft mapping not found.")

    gate = await _run_runtime_validation(request, packet, config)
    ok = gate["status"] == "pass"
    return {"ok": ok, "gate": gate}


@router.post("/{packet_id}/approve-activate")
async def approve_activate_packet(
    request: Request,
    packet_id: str,
    payload: ReviewDecisionPayload,
):
    repo = _repo(request)
    packet = await repo.find_one({"_id": packet_id})
    if packet is None:
        raise HTTPException(status_code=404, detail="Review packet not found.")
    if packet.status != ReviewPacketStatus.PENDING:
        raise HTTPException(status_code=400, detail="Only pending review packets can be approved.")
    if not _has_passing_runtime_gate(packet):
        raise HTTPException(status_code=400, detail="Runtime validation must pass before approval.")

    if payload.scope_type:
        packet.scope_type = payload.scope_type
        await repo.collection.update_one(
            {"_id": packet_id},
            {"$set": {"scopeType": payload.scope_type}}
        )
        if packet.source_file_id:
            db = _get_db(request)
            file_repo = ReconciliationFileRepository(db)
            await file_repo.update_one(
                {"_id": packet.source_file_id},
                {"scopeType": payload.scope_type}
            )

    post_approve_run = None
    if packet.draft_mapping_id:
        mapping_repo = MappingConfigRepository(_get_db(request))
        config = await mapping_repo.find_one({"_id": packet.draft_mapping_id})
        if config is not None and config.status == MappingConfigStatus.PENDING_APPROVAL:
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
            health.update({
                "stale": False,
                "status": MappingConfigStatus.APPROVED.value,
                "approvedAt": now,
                "reasoning": (health.get("reasoning") or "Approved from review packet."),
            })
            await mapping_repo.collection.update_one(
                {"_id": packet.draft_mapping_id},
                {"$set": {
                    "status": MappingConfigStatus.APPROVED.value,
                    "approvedAt": now,
                    "approvedBy": payload.reviewed_by,
                    "configHealth": health,
                }},
            )
            post_approve_run = await _reprocess_and_reconcile(request, packet, config)
    response = await _mark_packet(
        request,
        packet_id,
        ReviewPacketStatus.APPROVED,
        ReviewDecisionMode.APPROVE_ACTIVATE_NEXT_RUNTIME,
        payload.reviewed_by,
    )
    if post_approve_run is not None:
        response["postApproveRun"] = post_approve_run
        if not post_approve_run.get("ok", False):
            response["warning"] = (
                post_approve_run.get("reason")
                or "Approved, but post-approve processing did not complete."
            )
    return response


@router.post("/{packet_id}/approve-keep-current")
async def approve_keep_current_packet(
    request: Request,
    packet_id: str,
    payload: ReviewDecisionPayload,
):
    repo = _repo(request)
    packet = await repo.find_one({"_id": packet_id})
    if packet is None:
        raise HTTPException(status_code=404, detail="Review packet not found.")
    if not _has_passing_runtime_gate(packet):
        raise HTTPException(status_code=400, detail="Runtime validation must pass before approval.")

    if payload.scope_type:
        packet.scope_type = payload.scope_type
        await repo.collection.update_one(
            {"_id": packet_id},
            {"$set": {"scopeType": payload.scope_type}}
        )
        if packet.source_file_id:
            db = _get_db(request)
            file_repo = ReconciliationFileRepository(db)
            await file_repo.update_one(
                {"_id": packet.source_file_id},
                {"scopeType": payload.scope_type}
            )

    return await _mark_packet(
        request,
        packet_id,
        ReviewPacketStatus.APPROVED,
        ReviewDecisionMode.APPROVE_KEEP_CURRENT_FOR_FILE,
        payload.reviewed_by,
    )


@router.post("/{packet_id}/reject")
async def reject_packet(
    request: Request,
    packet_id: str,
    payload: ReviewDecisionPayload,
):
    return await _mark_packet(
        request,
        packet_id,
        ReviewPacketStatus.REJECTED,
        ReviewDecisionMode.REJECT,
        payload.reviewed_by,
    )


@router.post("/{packet_id}/send-to-studio")
async def send_packet_to_studio(
    request: Request,
    packet_id: str,
    payload: ReviewDecisionPayload,
):
    repo = _repo(request)
    packet = await repo.find_one({"_id": packet_id})
    if packet is None:
        raise HTTPException(status_code=404, detail="Review packet not found.")
    if packet.status != ReviewPacketStatus.PENDING:
        raise HTTPException(status_code=400, detail="Only pending review packets can be sent to mapping studio.")
    now = datetime.now(timezone.utc)
    await repo.collection.update_one(
        {"_id": packet_id},
        {"$set": {
            "decisionMode": ReviewDecisionMode.SEND_TO_MAPPING_STUDIO.value,
            "reviewedAt": now,
            "reviewedBy": payload.reviewed_by,
        }},
    )
    packet.decision_mode = ReviewDecisionMode.SEND_TO_MAPPING_STUDIO
    packet.reviewed_at = now
    packet.reviewed_by = payload.reviewed_by
    return {"ok": True, "packet": _serialize(packet)}
