"""Approval desk review packet endpoints."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.analysis.insights import invalidate_insight_cache
from src.config.ai_generator import generate_config_from_samples
from src.config.cache import ConfigCache
from src.config.loader import ConfigLoader
from src.config.validator import ConfigValidator
from src.core.constants import DEFAULT_CURRENCY
from src.core.enums import ProcessingStatus
from src.core.enums import FileType
from src.models.copilot_action import CopilotActionRepository, CopilotActionStatus
from src.models.mapping_config import MappingConfig, MappingConfigRepository, MappingConfigStatus
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


class DraftFieldMappingPayload(BaseModel):
    path: str
    column: Optional[int | str] = None
    type: str
    required: bool = False
    constant: Optional[str] = None
    sourceField: Optional[str] = None
    mapping: Optional[dict[str, str]] = None


class SaveDraftMappingPayload(BaseModel):
    sheet_name: str = Field(default="Sheet1", alias="sheetName")
    start_row: int = Field(default=2, alias="startRow")
    field_mappings: list[DraftFieldMappingPayload] = Field(alias="fieldMappings")


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


async def _next_pending_version(request: Request, partner: str) -> str:
    mapping_repo = MappingConfigRepository(_get_db(request))
    count = await mapping_repo.collection.count_documents({"partner": partner})
    return f"{partner}_v{count + 1:02d}"


def _canonicalize_guided_field_mappings(
    raw_mappings: list[dict],
) -> tuple[list[dict], list[str]]:
    normalized = [dict(item) for item in raw_mappings]
    warnings: list[str] = []
    paths = {item.get("path") for item in normalized if item.get("path")}

    if "currency" not in paths:
        normalized.append({
            "path": "currency",
            "type": "CONSTANT",
            "constant": DEFAULT_CURRENCY,
            "required": True,
        })
        warnings.append(f"Currency was not mapped, so a CONSTANT '{DEFAULT_CURRENCY}' mapping was added.")

    for item in normalized:
        if item.get("path") == "status" and str(item.get("type", "")).upper() == "STRING":
            item["type"] = "MAPPING"
            item["mapping"] = {
                "SUCCESS": "SUCCESS",
                "FAILED": "FAILED",
                "PENDING": "PENDING",
                "REVERSED": "REVERSED",
            }
            warnings.append("Status mapping was upgraded from STRING to MAPPING. Adjust status normalization if partner values differ.")

    return normalized, warnings


def _validate_guided_mapping_contract(config: MappingConfig) -> list[str]:
    errors = [err.reason for err in ConfigValidator.validate(config)]
    errors.extend(
        err.reason
        for err in ConfigValidator.validate_required_coverage(
            config, {"id", "amount", "status"} # currency is implicitly VND and not required
        )
    )
    return errors


def _serialize_mapping(config: MappingConfig) -> dict:
    data = config.model_dump(by_alias=True)
    data["_id"] = str(data["_id"])
    data["draftMappingId"] = data["_id"]
    if data.get("fileType") is not None:
        data["fileType"] = str(data["fileType"])
    return data


async def _resolve_ai_generation_context(request: Request, packet, existing_draft: MappingConfig | None):
    headers = []
    sample_rows = []
    header_row_index = None
    first_data_row_index = None

    packet_signature = getattr(packet, "structure_signature", None) or {}
    if packet_signature:
        headers = list(packet_signature.get("headers") or [])
        sample_rows = list(packet_signature.get("sampleRows") or [])
        header_row_index = packet_signature.get("headerRowIndex")
        first_data_row_index = packet_signature.get("firstDataRowIndex")

    if existing_draft is not None and not headers:
        draft_signature = getattr(existing_draft, "structure_signature", None) or {}
        headers = list(draft_signature.get("headers") or [])
        sample_rows = sample_rows or list(draft_signature.get("sampleRows") or [])
        header_row_index = header_row_index if header_row_index is not None else draft_signature.get("headerRowIndex")
        first_data_row_index = first_data_row_index if first_data_row_index is not None else draft_signature.get("firstDataRowIndex")

    if not headers:
        mapping_repo = MappingConfigRepository(_get_db(request))
        file_type_value = getattr(packet, "file_type_detected", None) or FileType.SETTLEMENT.value
        try:
            file_type = FileType(file_type_value)
        except ValueError:
            file_type = FileType.SETTLEMENT
        approved = await mapping_repo.find_by_partner_and_type(packet.partner, "UPC", file_type)
        if approved is not None:
            approved_signature = getattr(approved, "structure_signature", None) or {}
            headers = list(approved_signature.get("headers") or [])
            sample_rows = sample_rows or list(approved_signature.get("sampleRows") or [])
            header_row_index = header_row_index if header_row_index is not None else approved_signature.get("headerRowIndex")
            first_data_row_index = first_data_row_index if first_data_row_index is not None else approved_signature.get("firstDataRowIndex")

    if not sample_rows:
        packet_preview = getattr(packet, "sample_preview", None) or []
        sample_rows = [
            list(item.get("values") or [])
            for item in packet_preview
            if isinstance(item, dict) and isinstance(item.get("values"), list)
        ]

    return {
        "headers": headers,
        "sample_rows": sample_rows,
        "header_row_index": header_row_index,
        "first_data_row_index": first_data_row_index,
    }


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
    sampled_rows = 0
    success_rows = 0
    failed_rows = 0
    failed_examples: list[dict] = []
    normalizer = TransactionNormalizer(config.field_mappings)

    def _consume_row(row: list, row_number: int) -> None:
        nonlocal sampled_rows, success_rows, failed_rows, failed_examples
        sampled_rows += 1
        norm_result = normalizer.normalize(row, row_number)
        if norm_result.errors:
            failed_rows += 1
            failed_examples.append({
                "row": row_number,
                "reason": norm_result.errors[0].reason,
                "field": norm_result.errors[0].field,
            })
            return
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

    if source_file_path:
        path = Path(source_file_path)
        if path.exists():
            with create_reader(source_file_path, config) as reader:
                for row in reader.iter_rows():
                    row_number = config.start_row + sampled_rows
                    _consume_row(row, row_number)
                    if sampled_rows >= 20:
                        break
        else:
            return {
                "gateKey": "runtime_validation",
                "label": "Runtime validation",
                "status": "fail",
                "reason": f"Source file is not available at {source_file_path}.",
                "details": {"successRows": 0, "failedRows": 0, "sampledRows": 0},
            }
    else:
        sample_preview = getattr(packet, "sample_preview", None) or []
        for idx, sample in enumerate(sample_preview[:20]):
            row = sample.get("values") if isinstance(sample, dict) else None
            if not isinstance(row, list):
                continue
            row_number = int(sample.get("rowIndex") or (config.start_row + idx)) if isinstance(sample, dict) else (config.start_row + idx)
            _consume_row(row, row_number)

        if sampled_rows == 0:
            return {
                "gateKey": "runtime_validation",
                "label": "Runtime validation",
                "status": "fail",
                "reason": "No source file path or sample preview is attached to this review packet.",
                "details": {"successRows": 0, "failedRows": 0, "sampledRows": 0},
            }

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


@router.post("/{packet_id}/generate-ai-mapping")
async def generate_ai_mapping_for_packet(request: Request, packet_id: str):
    repo = _repo(request)
    packet = await repo.find_one({"_id": packet_id})
    if packet is None:
        raise HTTPException(status_code=404, detail="Review packet not found.")
    if packet.status != ReviewPacketStatus.PENDING:
        raise HTTPException(status_code=400, detail="Only pending review packets can be regenerated.")

    mapping_repo = MappingConfigRepository(_get_db(request))
    existing = None
    if packet.draft_mapping_id:
        existing = await mapping_repo.find_one({"_id": packet.draft_mapping_id})

    context = await _resolve_ai_generation_context(request, packet, existing)
    headers = context["headers"]
    sample_rows = context["sample_rows"]
    if not headers:
        raise HTTPException(status_code=400, detail="No header signature is attached to this review packet.")
    if not sample_rows:
        raise HTTPException(status_code=400, detail="No sample rows are attached to this review packet.")

    config_dict, error = await generate_config_from_samples(
        partner=packet.partner,
        headers=headers,
        sample_rows=sample_rows,
        known_constants={"provider": packet.partner},
        header_row_index=context["header_row_index"],
        first_data_row_index=context["first_data_row_index"] or packet.parse_strategy.get("startRow") or 2,
    )
    if error or config_dict is None:
        raise HTTPException(status_code=500, detail=f"AI mapping generation failed: {error}")

    field_mappings, mapping_warnings = _canonicalize_guided_field_mappings(
        [
            item.model_dump(by_alias=True) if hasattr(item, "model_dump") else dict(item)
            for item in (config_dict.get("fieldMappings") or [])
        ]
    )

    file_type_value = getattr(packet, "file_type_detected", None) or FileType.SETTLEMENT.value
    try:
        file_type = FileType(file_type_value)
    except ValueError:
        file_type = FileType.SETTLEMENT
    workflow_type = getattr(existing, "workflow_type", None) or packet.parse_strategy.get("workflowType") or "UPC"
    structure_signature = {
        "headers": headers,
        "sampleRows": sample_rows[:10],
        "headerRowIndex": context["header_row_index"],
        "firstDataRowIndex": context["first_data_row_index"] or packet.parse_strategy.get("startRow") or 2,
        "columnCount": len(headers),
    }
    now = datetime.now(timezone.utc)
    config_health = {
        "stale": False,
        "status": MappingConfigStatus.PENDING_APPROVAL.value,
        "source": "ai_generated",
        "confidence": config_dict.get("confidence") or 0.85,
        "reasoning": config_dict.get("reasoning") or "Automatically generated by AI from review packet samples.",
        "updatedAt": now,
    }

    if existing is not None and existing.status == MappingConfigStatus.PENDING_APPROVAL:
        await mapping_repo.collection.update_one(
            {"_id": str(existing.id)},
            {"$set": {
                "sheetName": config_dict.get("sheetName") or existing.sheet_name or "Sheet1",
                "startRow": config_dict.get("startRow") or existing.start_row or packet.parse_strategy.get("startRow") or 2,
                "fieldMappings": field_mappings,
                "structureSignature": structure_signature,
                "configHealth": config_health,
                "status": MappingConfigStatus.PENDING_APPROVAL.value,
                "fileType": file_type.value,
                "workflowType": workflow_type,
            }},
        )
        draft_id = str(existing.id)
        updated = await mapping_repo.find_one({"_id": draft_id})
        mapping = updated or existing
    else:
        mapping = MappingConfig(
            partner=packet.partner,
            workflowType=workflow_type,
            fileType=file_type,
            sheetName=config_dict.get("sheetName") or "Sheet1",
            startRow=config_dict.get("startRow") or packet.parse_strategy.get("startRow") or 2,
            fieldMappings=field_mappings,
            configVersion=getattr(existing, "config_version", None) if existing is not None else await _next_pending_version(request, packet.partner),
            structureSignature=structure_signature,
            status=MappingConfigStatus.PENDING_APPROVAL,
            configHealth=config_health,
        )
        await mapping_repo.create(mapping)
        draft_id = str(mapping.id)
        await repo.collection.update_one({"_id": packet_id}, {"$set": {"draftMappingId": draft_id}})

    validation_gates = [
        dict(gate) for gate in (packet.validation_gates or [])
        if gate.get("gateKey") != "runtime_validation"
    ]
    await repo.collection.update_one(
        {"_id": packet_id},
        {"$set": {
            "draftMappingId": draft_id,
            "parseStrategy": {
                **(packet.parse_strategy or {}),
                "sheetName": config_dict.get("sheetName") or packet.parse_strategy.get("sheetName") or "Sheet1",
                "startRow": config_dict.get("startRow") or packet.parse_strategy.get("startRow") or 2,
                "fieldMappingCount": len(field_mappings),
                "strategy": "AI regenerated draft mapping from review packet samples",
            },
            "validationGates": validation_gates,
        }},
    )

    mapping_payload = _serialize_mapping(mapping if isinstance(mapping, MappingConfig) else updated)
    return {
        "ok": True,
        "draftMappingId": draft_id,
        "mapping": mapping_payload,
        "warnings": mapping_warnings,
        "validationGates": validation_gates,
    }


@router.post("/{packet_id}/save-draft-mapping")
async def save_draft_mapping_for_packet(
    request: Request,
    packet_id: str,
    payload: SaveDraftMappingPayload,
):
    repo = _repo(request)
    packet = await repo.find_one({"_id": packet_id})
    if packet is None:
        raise HTTPException(status_code=404, detail="Review packet not found.")
    if packet.status != ReviewPacketStatus.PENDING:
        raise HTTPException(status_code=400, detail="Only pending review packets can be edited.")

    mapping_repo = MappingConfigRepository(_get_db(request))
    existing = None
    if packet.draft_mapping_id:
        existing = await mapping_repo.find_one({"_id": packet.draft_mapping_id})

    file_type_value = getattr(packet, "file_type_detected", None) or FileType.SETTLEMENT.value
    try:
        file_type = FileType(file_type_value)
    except ValueError:
        file_type = FileType.SETTLEMENT
    workflow_type = None
    if existing is not None:
        workflow_type = existing.workflow_type
    workflow_type = workflow_type or packet.parse_strategy.get("workflowType") or "UPC"

    field_mappings, mapping_warnings = _canonicalize_guided_field_mappings(
        [item.model_dump(by_alias=True) for item in payload.field_mappings]
    )
    now = datetime.now(timezone.utc)
    config_health = {
        "stale": False,
        "status": MappingConfigStatus.PENDING_APPROVAL.value,
        "confidence": 0.95,
        "reasoning": "Updated from Guided Review inline mapping edits.",
        "updatedAt": now,
    }

    candidate_config = MappingConfig(
        partner=packet.partner,
        workflowType=workflow_type,
        fileType=file_type,
        sheetName=payload.sheet_name,
        startRow=payload.start_row,
        fieldMappings=field_mappings,
        configVersion=getattr(existing, "config_version", None) if existing is not None else None,
        structureSignature=packet.structure_signature,
        status=MappingConfigStatus.PENDING_APPROVAL,
        configHealth=config_health,
    )
    validation_errors = _validate_guided_mapping_contract(candidate_config)
    if validation_errors:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Draft mapping is incomplete or invalid.",
                "errors": validation_errors,
                "warnings": mapping_warnings,
            },
        )

    if existing is not None:
        await mapping_repo.collection.update_one(
            {"_id": str(existing.id)},
            {"$set": {
                "sheetName": payload.sheet_name,
                "startRow": payload.start_row,
                "fieldMappings": field_mappings,
                "status": MappingConfigStatus.PENDING_APPROVAL.value,
                "configHealth": config_health,
                "structureSignature": packet.structure_signature,
                "workflowType": workflow_type,
                "fileType": file_type.value,
            }},
        )
        draft_mapping_id = str(existing.id)
    else:
        proposal = MappingConfig(
            partner=packet.partner,
            workflowType=workflow_type,
            fileType=file_type,
            sheetName=payload.sheet_name,
            startRow=payload.start_row,
            fieldMappings=field_mappings,
            configVersion=await _next_pending_version(request, packet.partner),
            structureSignature=packet.structure_signature,
            status=MappingConfigStatus.PENDING_APPROVAL,
            configHealth=config_health,
        )
        await mapping_repo.create(proposal)
        draft_mapping_id = str(proposal.id)

    validation_gates = [dict(gate) for gate in (packet.validation_gates or []) if gate.get("gateKey") != "runtime_validation"]
    await repo.collection.update_one(
        {"_id": packet_id},
        {"$set": {
            "draftMappingId": draft_mapping_id,
            "parseStrategy.sheetName": payload.sheet_name,
            "parseStrategy.startRow": payload.start_row,
            "parseStrategy.fieldMappingCount": len(field_mappings),
            "validationGates": validation_gates,
        }},
    )
    return {
        "ok": True,
        "draftMappingId": draft_mapping_id,
        "fieldMappingCount": len(field_mappings),
        "sheetName": payload.sheet_name,
        "startRow": payload.start_row,
        "warnings": mapping_warnings,
        "validationGates": validation_gates,
    }


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


@router.post("/from-mapping/{mapping_id}")
async def create_review_packet_from_mapping(
    request: Request,
    mapping_id: str,
):
    """Create a pending review packet from a completed mapping config (Studio handoff)."""
    mapping_repo = MappingConfigRepository(_get_db(request))
    mapping = await mapping_repo.find_one({"_id": mapping_id})
    if mapping is None:
        raise HTTPException(status_code=404, detail="Mapping config not found.")

    packet = ReviewPacket(
        source_type=ReviewPacketSourceType.STUDIO_HANDOFF,
        partner=mapping.partner,
        file_name=mapping.sheet_name or "Manual Configuration",
        file_type_detected=mapping.file_type or "SETTLEMENT",
        structure_signature=mapping.structure_signature,
        draft_mapping_id=mapping_id,
        parse_strategy={
            "sheetName": mapping.sheet_name,
            "startRow": mapping.start_row,
            "fieldMappingCount": len(mapping.field_mappings or []),
        },
        risk_summary={
            "severity": "medium",
            "summary": "Draft mapping handed off from Mapping Studio for review.",
        },
        recommended_action={
            "actionType": "APPROVE_REQUIRED_BEFORE_RUNTIME",
            "reason": "Draft mapping ready for review and approval.",
        },
    )
    repo = _repo(request)
    created = await repo.create(packet)
    return {"ok": True, "packet": _serialize(created)}
