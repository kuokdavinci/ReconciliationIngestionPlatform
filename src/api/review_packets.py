"""Approval desk review packet endpoints."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.api.actor import require_actor
from src.config.ai_generator import generate_config_from_samples
from src.core.enums import FileType
from src.models.mapping_config import MappingConfig, MappingConfigRepository, MappingConfigStatus
from src.models.post_approval_run import PostApprovalRunRepository
from src.models.review_packet import (
    ReviewPacket,
    ReviewDecisionMode,
    ReviewPacketRepository,
    ReviewPacketSourceType,
    ReviewPacketStatus,
)
from src.services.mapping_contract import (
    canonicalize_field_mappings,
    serialize_field_mappings,
    validate_mapping_contract,
)
from src.services.review_packet_actions import (
    approve_packet_mapping_and_reprocess,
    build_config_loader,
    mark_packet,
    serialize_post_approval_run,
    update_packet_scope,
)
from src.services.ai_mapping_context import resolve_ai_generation_context
from src.services.runtime_validation import (
    derive_validation_state,
    run_runtime_validation,
)


router = APIRouter(prefix="/api/v1/review-packets")


def _get_db(request: Request):
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available.")
    return db


def _repo(request: Request) -> ReviewPacketRepository:
    return ReviewPacketRepository(_get_db(request))


def _config_loader(request: Request):
    return build_config_loader(request)


def _serialize(packet) -> dict:
    data = packet.model_dump(by_alias=True)
    data["_id"] = str(data["_id"])
    data["reviewItemId"] = data["_id"]
    data["validationState"] = _derive_validation_state(packet.validation_gates or [])
    return data



class ReviewDecisionPayload(BaseModel):
    reviewed_by: Optional[str] = Field(default=None, alias="reviewedBy")
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


def _derive_validation_state(validation_gates: list[dict]) -> str:
    runtime_gate = next(
        (gate for gate in validation_gates if gate.get("gateKey") == "runtime_validation"),
        None,
    )
    if runtime_gate is None:
        return "NOT_RUN"
    return derive_validation_state(runtime_gate)


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


@router.get("/{packet_id}/post-approve-run")
async def get_post_approve_run(request: Request, packet_id: str):
    run = await PostApprovalRunRepository(_get_db(request)).find_latest_by_packet_id(packet_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Post-approval run not found.")
    return {"run": serialize_post_approval_run(run)}


async def _next_pending_version(request: Request, partner: str) -> str:
    mapping_repo = MappingConfigRepository(_get_db(request))
    return await mapping_repo.allocate_next_version(partner)


def _serialize_mapping(config: MappingConfig) -> dict:
    data = config.model_dump(by_alias=True)
    data["_id"] = str(data["_id"])
    data["draftMappingId"] = data["_id"]
    data["draftMappingVersion"] = data.get("configVersion") or data["_id"]
    if data.get("fileType") is not None:
        data["fileType"] = str(data["fileType"])
    return data



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

    gate = await run_runtime_validation(_get_db(request), packet, config)
    ok = gate["status"] == "pass"
    return {"ok": ok, "validationState": derive_validation_state(gate), "gate": gate}


@router.post("/{packet_id}/generate-ai-mapping")
async def generate_ai_mapping_for_packet(request: Request, packet_id: str, force: bool = False):
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

    # Optimization: If draft mapping already exists with mapping fields and force is False, return it directly
    if existing is not None and getattr(existing, "field_mappings", None) and not force:
        mapping_payload = _serialize_mapping(existing)
        return {
            "ok": True,
            "mapping": mapping_payload,
            "warnings": []
        }

    context = await resolve_ai_generation_context(_get_db(request), packet, existing)
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

    field_mappings, mapping_warnings = canonicalize_field_mappings(
        serialize_field_mappings(config_dict.get("fieldMappings") or [])
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
        await repo.collection.update_one(
            {"_id": packet_id},
            {"$set": {
                "draftMappingId": draft_id,
                "draftMappingVersion": getattr(mapping, "config_version", None) or draft_id,
            }},
        )

    validation_gates = [
        dict(gate) for gate in (packet.validation_gates or [])
        if gate.get("gateKey") != "runtime_validation"
    ]
    mapping_payload = _serialize_mapping(mapping if isinstance(mapping, MappingConfig) else updated)
    await repo.collection.update_one(
        {"_id": packet_id},
        {"$set": {
            "draftMappingId": draft_id,
            "draftMappingVersion": mapping_payload["draftMappingVersion"],
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
    return {
        "ok": True,
        "draftMappingId": draft_id,
        "draftMappingVersion": mapping_payload["draftMappingVersion"],
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

    field_mappings, mapping_warnings = canonicalize_field_mappings(
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
    contract_validation = validate_mapping_contract(candidate_config)
    validation_warnings = [
        warning for warning in contract_validation.warnings if warning not in mapping_warnings
    ]
    if contract_validation.errors:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Draft mapping is incomplete or invalid.",
                "errors": contract_validation.errors,
                "warnings": mapping_warnings + validation_warnings,
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

    draft_mapping_version = (
        getattr(existing, "config_version", None)
        if existing is not None
        else getattr(proposal, "config_version", None)
    ) or draft_mapping_id
    validation_gates = [dict(gate) for gate in (packet.validation_gates or []) if gate.get("gateKey") != "runtime_validation"]
    await repo.collection.update_one(
        {"_id": packet_id},
        {"$set": {
            "draftMappingId": draft_mapping_id,
            "draftMappingVersion": draft_mapping_version,
            "parseStrategy.sheetName": payload.sheet_name,
            "parseStrategy.startRow": payload.start_row,
            "parseStrategy.fieldMappingCount": len(field_mappings),
            "validationGates": validation_gates,
        }},
    )
    return {
        "ok": True,
        "draftMappingId": draft_mapping_id,
        "draftMappingVersion": draft_mapping_version,
        "fieldMappingCount": len(field_mappings),
        "sheetName": payload.sheet_name,
        "startRow": payload.start_row,
        "warnings": mapping_warnings + validation_warnings,
        "validationGates": validation_gates,
    }


async def approve_activate_packet_action(
    request: Request,
    packet_id: str,
    payload: ReviewDecisionPayload,
):
    payload.reviewed_by = require_actor(request, payload_actor=payload.reviewed_by)
    repo = _repo(request)
    packet = await repo.find_one({"_id": packet_id})
    if packet is None:
        raise HTTPException(status_code=404, detail="Review packet not found.")
    if packet.status != ReviewPacketStatus.PENDING:
        raise HTTPException(status_code=400, detail="Only pending review packets can be approved.")
    if not _has_passing_runtime_gate(packet):
        raise HTTPException(status_code=400, detail="Runtime validation must pass before approval.")

    await update_packet_scope(request, packet_id, packet, payload.scope_type)

    post_approve_run = await approve_packet_mapping_and_reprocess(
        request,
        packet,
        payload.reviewed_by,
    )
    response = await mark_packet(
        request,
        packet_id,
        ReviewPacketStatus.APPROVED,
        ReviewDecisionMode.APPROVE_ACTIVATE_NEXT_RUNTIME,
        payload.reviewed_by,
        _serialize,
    )
    if post_approve_run is not None:
        response["postApproveRun"] = post_approve_run
    return response


@router.post("/{packet_id}/approve-activate")
async def approve_activate_packet(
    request: Request,
    packet_id: str,
    payload: ReviewDecisionPayload,
):
    return await approve_activate_packet_action(request, packet_id, payload)


async def approve_keep_current_packet_action(
    request: Request,
    packet_id: str,
    payload: ReviewDecisionPayload,
):
    payload.reviewed_by = require_actor(request, payload_actor=payload.reviewed_by)
    repo = _repo(request)
    packet = await repo.find_one({"_id": packet_id})
    if packet is None:
        raise HTTPException(status_code=404, detail="Review packet not found.")
    if not _has_passing_runtime_gate(packet):
        raise HTTPException(status_code=400, detail="Runtime validation must pass before approval.")

    await update_packet_scope(request, packet_id, packet, payload.scope_type)

    return await mark_packet(
        request,
        packet_id,
        ReviewPacketStatus.APPROVED,
        ReviewDecisionMode.APPROVE_KEEP_CURRENT_FOR_FILE,
        payload.reviewed_by,
        _serialize,
    )


@router.post("/{packet_id}/approve-keep-current")
async def approve_keep_current_packet(
    request: Request,
    packet_id: str,
    payload: ReviewDecisionPayload,
):
    return await approve_keep_current_packet_action(request, packet_id, payload)


async def reject_packet_action(
    request: Request,
    packet_id: str,
    payload: ReviewDecisionPayload,
):
    payload.reviewed_by = require_actor(request, payload_actor=payload.reviewed_by)
    return await mark_packet(
        request,
        packet_id,
        ReviewPacketStatus.REJECTED,
        ReviewDecisionMode.REJECT,
        payload.reviewed_by,
        _serialize,
    )


@router.post("/{packet_id}/reject")
async def reject_packet(
    request: Request,
    packet_id: str,
    payload: ReviewDecisionPayload,
):
    return await reject_packet_action(request, packet_id, payload)


@router.post("/{packet_id}/send-to-studio")
async def send_packet_to_studio(
    request: Request,
    packet_id: str,
    payload: ReviewDecisionPayload,
):
    payload.reviewed_by = require_actor(request, payload_actor=payload.reviewed_by)
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


@router.post("/{packet_id}/classify-scope-llm")
async def classify_scope_llm_for_packet(request: Request, packet_id: str, force: bool = False):
    import re
    import os
    import json
    import logging
    from datetime import datetime, time as datetime_time
    from src.analysis.config import AnalysisConfig
    from src.analysis.provider import create_provider
    from src.readers import create_reader
    from src.models.mapping_config import MappingConfigRepository
    
    logger = logging.getLogger(__name__)
    repo = _repo(request)
    packet = await repo.find_one({"_id": packet_id})
    if packet is None:
        raise HTTPException(status_code=404, detail="Review packet not found.")
        
    # Optimization: If scope is already classified and force is False, return it directly
    if getattr(packet, "scope_type", None) and not force:
        suggested = packet.scope_type
        probs = {
            "FULL_SNAPSHOT": 1.0 if suggested == "FULL_SNAPSHOT" else 0.0,
            "INCREMENTAL_APPEND": 1.0 if suggested == "INCREMENTAL_APPEND" else 0.0,
            "REPLACEMENT": 1.0 if suggested == "REPLACEMENT" else 0.0,
        }
        db = _get_db(request)
        recon_date = getattr(packet, "reconciliation_date", None)
        if not recon_date:
            match = re.search(r'(\d{4})[-_]?(\d{2})[-_]?(\d{2})', packet.file_name)
            if match:
                try:
                    recon_date = datetime.strptime(f"{match.group(1)}-{match.group(2)}-{match.group(3)}", "%Y-%m-%d")
                except ValueError:
                    recon_date = datetime.utcnow()
            else:
                recon_date = datetime.utcnow()
                
        start_of_day = datetime.combine(recon_date, datetime_time.min)
        end_of_day = datetime.combine(recon_date, datetime_time.max)
        
        internal_count = await db["internal_transaction"].count_documents({
            "partner": packet.partner,
            "transactionTime": {
                "$gte": start_of_day,
                "$lte": end_of_day
            }
        })
        
        received_count = 0
        source_file_path = getattr(packet, "source_file_path", None)
        if source_file_path and os.path.exists(source_file_path):
            try:
                mapping_repo = MappingConfigRepository(db)
                config = None
                if packet.draft_mapping_id:
                    config = await mapping_repo.find_one({"_id": packet.draft_mapping_id})
                with create_reader(source_file_path, config) as reader:
                    received_count = sum(1 for _ in reader.iter_rows())
            except Exception as exc:
                logger.error(f"Error counting rows in file: {exc}")
                received_count = len(packet.structure_signature.get("sampleRows", [])) if packet.structure_signature else 0
        else:
            received_count = len(packet.structure_signature.get("sampleRows", [])) if packet.structure_signature else 0

        return {
            "ok": True,
            "internalDbRecordCount": internal_count,
            "receivedRecordCount": received_count,
            "probabilities": probs,
            "suggestedScope": suggested,
            "reasoning": getattr(packet, "scope_reason", None) or "Reused previously computed scope from review packet."
        }

    db = _get_db(request)
    
    # 1. Determine date
    recon_date = getattr(packet, "reconciliation_date", None)
    if not recon_date:
        match = re.search(r'(\d{4})[-_]?(\d{2})[-_]?(\d{2})', packet.file_name)
        if match:
            try:
                recon_date = datetime.strptime(f"{match.group(1)}-{match.group(2)}-{match.group(3)}", "%Y-%m-%d")
            except ValueError:
                recon_date = datetime.utcnow()
        else:
            recon_date = datetime.utcnow()
            
    # 2. Count internal transactions
    start_of_day = datetime.combine(recon_date, datetime_time.min)
    end_of_day = datetime.combine(recon_date, datetime_time.max)
    
    internal_count = await db["internal_transaction"].count_documents({
        "partner": packet.partner,
        "transactionTime": {
            "$gte": start_of_day,
            "$lte": end_of_day
        }
    })
    
    # 3. Count received records
    received_count = 0
    source_file_path = getattr(packet, "source_file_path", None)
    if source_file_path and os.path.exists(source_file_path):
        try:
            mapping_repo = MappingConfigRepository(db)
            config = None
            if packet.draft_mapping_id:
                config = await mapping_repo.find_one({"_id": packet.draft_mapping_id})
            with create_reader(source_file_path, config) as reader:
                received_count = sum(1 for _ in reader.iter_rows())
        except Exception as exc:
            logger.error(f"Error counting rows in file: {exc}")
            received_count = len(packet.structure_signature.get("sampleRows", [])) if packet.structure_signature else 0
    else:
        received_count = len(packet.structure_signature.get("sampleRows", [])) if packet.structure_signature else 0
        
    # 4. Invoke LLM for classification probabilities
    llm_provider = create_provider(AnalysisConfig())
    system_prompt = (
        "You are an expert reconciliation assistant. Your task is to analyze the file metadata and database status "
        "and classify the reconciliation file scope. You must respond ONLY with a valid JSON object."
    )
    
    prompt = f"""Classify the reconciliation file's scope into one of these types:
1. FULL_SNAPSHOT: The file contains the full set of transactions for the day, replacing the existing state. Usually if internal DB has 0 records, or matches the file count.
2. INCREMENTAL_APPEND: The file contains a new batch/wave of transactions for the day, to be appended to existing ones. Usually if internal DB already has records and this file adds more.
3. REPLACEMENT: The file contains corrections/retry records for transactions that already exist, which should overwrite them.

Metadata:
- Partner: {packet.partner}
- File Name: {packet.file_name}
- Received Record Count: {received_count}
- Internal DB Record Count (same day): {internal_count}

Analyze the filename hints (e.g., words like 'append', 'snapshot', 'replace', 'delta', 'correction', 'retry') and compare Received Record Count vs Internal DB Record Count.
Return a JSON object containing:
- probabilities: a dictionary with keys "FULL_SNAPSHOT", "INCREMENTAL_APPEND", "REPLACEMENT" and float values (probabilities summing to 1.0 or 100%)
- suggested_scope: one of the three category strings
- reasoning: a brief explanation in English

JSON format:
{{
  "probabilities": {{
    "FULL_SNAPSHOT": 0.8,
    "INCREMENTAL_APPEND": 0.15,
    "REPLACEMENT": 0.05
  }},
  "suggested_scope": "FULL_SNAPSHOT",
  "reasoning": "<explanation>"
}}
"""
    try:
        response_text = await llm_provider.generate(prompt=prompt, system_prompt=system_prompt)
        clean_text = response_text.strip()
        if clean_text.startswith("```"):
            parts = clean_text.split("```")
            if len(parts) >= 3:
                clean_text = parts[1]
                if clean_text.startswith("json"):
                    clean_text = clean_text[4:]
        clean_text = clean_text.strip()
        result = json.loads(clean_text)
    except Exception as exc:
        logger.error(f"LLM classification failed: {exc}")
        result = {
            "probabilities": {
                "FULL_SNAPSHOT": 0.34,
                "INCREMENTAL_APPEND": 0.33,
                "REPLACEMENT": 0.33
            },
            "suggested_scope": "FULL_SNAPSHOT",
            "reasoning": f"Fallback suggestion due to LLM error: {str(exc)}"
        }
        
    return {
        "ok": True,
        "internalDbRecordCount": internal_count,
        "receivedRecordCount": received_count,
        "probabilities": result.get("probabilities", {}),
        "suggestedScope": result.get("suggested_scope", "FULL_SNAPSHOT"),
        "reasoning": result.get("reasoning", "")
    }


class ScopeUpdatePayload(BaseModel):
    scope_type: str = Field(alias="scopeType")


@router.post("/{packet_id}/scope")
async def update_packet_scope_endpoint(request: Request, packet_id: str, payload: ScopeUpdatePayload):
    from src.services.review_packet_actions import update_packet_scope
    repo = _repo(request)
    packet = await repo.find_one({"_id": packet_id})
    if packet is None:
        raise HTTPException(status_code=404, detail="Review packet not found.")
        
    await update_packet_scope(request, packet_id, packet, payload.scope_type)
    return {"ok": True, "scopeType": payload.scope_type}
