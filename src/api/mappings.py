"""FastAPI routers for mapping configs and approval-driven proposals."""

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from src.api.actor import require_actor
from src.analysis.insights import invalidate_insight_cache
from src.config.ai_generator import generate_config_from_samples
from src.config.settings import settings
from src.config.signature import compute_signature
from src.core.enums import FileType
from src.models.copilot_action import (
    CopilotAction,
    CopilotActionRepository,
    CopilotActionStatus,
    CopilotActionType,
)
from src.models.mapping_config import (
    MappingConfig,
    MappingConfigRepository,
    MappingConfigStatus,
)
from src.models.review_packet import (
    ReviewPacketStatus,
    ReviewPacket,
    ReviewPacketRepository,
    ReviewPacketSourceType,
)
from src.reconciliation.scope import classify_scope
from src.services.audit import record_audit_event
from src.services.mapping_contract import (
    canonicalize_field_mappings,
    serialize_field_mappings,
    validate_mapping_contract,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/mappings")
router_v2 = APIRouter(prefix="/api/v1/mapping")

try:
    import python_multipart  # noqa: F401
    _MULTIPART_AVAILABLE = True
except ImportError:
    _MULTIPART_AVAILABLE = False


def _get_upload_tmp_dir() -> Path:
    temp_dir = Path(settings.upload_tmp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def _validate_partner(partner: Optional[str]) -> Optional[str]:
    if partner is not None and not partner.strip():
        raise HTTPException(status_code=400, detail="Partner identifier cannot be empty.")
    return partner.strip() if partner else None


def _get_db(request: Request):
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available.")
    return db


def _get_repo(request: Request) -> MappingConfigRepository:
    return MappingConfigRepository(_get_db(request))


def _get_action_repo(request: Request) -> CopilotActionRepository:
    return CopilotActionRepository(_get_db(request))


def _get_review_packet_repo(request: Request) -> ReviewPacketRepository:
    return ReviewPacketRepository(_get_db(request))


def _serialize_config(config: MappingConfig) -> dict:
    data = config.model_dump(by_alias=True)
    data["_id"] = str(data["_id"])
    if data.get("fileType") is not None:
        data["fileType"] = str(data["fileType"])
    data["draftMappingId"] = data["_id"]
    return data


async def _sync_action_for_config(
    request: Request,
    config_id: str,
    status: CopilotActionStatus,
    reviewed_by: str | None,
) -> None:
    await _get_action_repo(request).collection.update_many(
        {
            "$or": [{"draftMappingId": config_id}, {"targetConfigId": config_id}],
            "status": CopilotActionStatus.PENDING_APPROVAL.value,
        },
        {
            "$set": {
                "status": status.value,
                "reviewedAt": datetime.now(timezone.utc),
                "reviewedBy": reviewed_by,
            }
        },
    )


async def _sync_review_packets_for_config(
    request: Request,
    config_id: str,
    status: ReviewPacketStatus,
) -> None:
    await _get_review_packet_repo(request).collection.update_many(
        {
            "$or": [{"draftMappingId": config_id}, {"proposalConfigId": config_id}],
            "status": "PENDING",
        },
        {
            "$set": {
                "status": status.value,
                "reviewedAt": datetime.now(timezone.utc),
            }
        },
    )


class MappingReviewPayload(BaseModel):
    confidence: float | None = None
    reasoning: str | None = None
    reviewed_by: str | None = Field(default=None, alias="reviewedBy")


@router.get("")
async def list_mappings(
    request: Request,
    partner: Optional[str] = Query(default=None),
):
    partner = _validate_partner(partner)
    try:
        repo = _get_repo(request)
        query: dict = {}
        if partner:
            query["partner"] = partner
        records = await repo.find_many(query)
        return {"mappings": [_serialize_config(record) for record in records]}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error listing mappings: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list mappings: {str(exc)}",
        )


async def approve_mapping_config_action(
    request: Request,
    config_id: str,
    payload: MappingReviewPayload,
):
    payload.reviewed_by = require_actor(request, payload_actor=payload.reviewed_by)
    repo = _get_repo(request)
    config = await repo.find_one({"_id": config_id})
    if config is None:
        raise HTTPException(status_code=404, detail="Mapping config not found.")
    if config.status != MappingConfigStatus.PENDING_APPROVAL:
        raise HTTPException(status_code=400, detail="Only pending configs can be approved.")

    now = datetime.now(timezone.utc)
    current_approved = await repo.find_by_partner_and_type(
        config.partner, config.workflow_type, config.file_type
    )
    if current_approved is not None:
        await repo.collection.update_one(
            {"_id": str(current_approved.id)},
            {
                "$set": {
                    "status": MappingConfigStatus.SUPERSEDED.value,
                    "supersededAt": now,
                    "supersededByConfigId": str(config.id),
                }
            },
        )

    health = dict(config.config_health or {})
    health.update(
        {
            "stale": False,
            "status": MappingConfigStatus.APPROVED.value,
            "approvedAt": now,
        }
    )
    if payload.confidence is not None:
        health["confidence"] = payload.confidence
    if payload.reasoning is not None:
        health["reasoning"] = payload.reasoning

    await repo.collection.update_one(
        {"_id": config_id},
        {
            "$set": {
                "status": MappingConfigStatus.APPROVED.value,
                "approvedAt": now,
                "approvedBy": payload.reviewed_by,
                "configHealth": health,
            }
        },
    )
    await _sync_action_for_config(
        request, config_id, CopilotActionStatus.APPROVED, payload.reviewed_by
    )
    await _sync_review_packets_for_config(
        request, config_id, ReviewPacketStatus.APPROVED
    )

    config.status = MappingConfigStatus.APPROVED
    config.approved_at = now
    config.approved_by = payload.reviewed_by
    config.config_health = health

    try:
        await invalidate_insight_cache(config.partner, date="")
    except Exception as cache_exc:
        logger.error(f"Failed to invalidate insight cache for {config.partner}: {cache_exc}")

    await record_audit_event(
        _get_db(request),
        entity_type="MAPPING_CONFIG",
        entity_id=config_id,
        action="APPROVED",
        actor=payload.reviewed_by,
        metadata={
            "partner": config.partner,
            "reference": getattr(config, "config_version", None) or str(config.id),
            "mappingVersion": getattr(config, "config_version", None) or str(config.id),
            "status": config.status.value,
        },
    )

    return {"ok": True, "mapping": _serialize_config(config)}


@router.post("/{config_id}/approve")
async def approve_mapping_config(
    request: Request,
    config_id: str,
    payload: MappingReviewPayload,
):
    return await approve_mapping_config_action(request, config_id, payload)


async def reject_mapping_config_action(
    request: Request,
    config_id: str,
    payload: MappingReviewPayload,
):
    payload.reviewed_by = require_actor(request, payload_actor=payload.reviewed_by)
    repo = _get_repo(request)
    config = await repo.find_one({"_id": config_id})
    if config is None:
        raise HTTPException(status_code=404, detail="Mapping config not found.")
    if config.status != MappingConfigStatus.PENDING_APPROVAL:
        raise HTTPException(status_code=400, detail="Only pending configs can be rejected.")

    health = dict(config.config_health or {})
    health.update({"status": MappingConfigStatus.REJECTED.value})
    await repo.collection.update_one(
        {"_id": config_id},
        {
            "$set": {
                "status": MappingConfigStatus.REJECTED.value,
                "configHealth": health,
            }
        },
    )
    await _sync_action_for_config(
        request, config_id, CopilotActionStatus.REJECTED, payload.reviewed_by
    )
    await _sync_review_packets_for_config(
        request, config_id, ReviewPacketStatus.REJECTED
    )
    config.status = MappingConfigStatus.REJECTED
    config.config_health = health
    await record_audit_event(
        _get_db(request),
        entity_type="MAPPING_CONFIG",
        entity_id=config_id,
        action="REJECTED",
        actor=payload.reviewed_by,
        metadata={
            "partner": config.partner,
            "reference": getattr(config, "config_version", None) or str(config.id),
            "mappingVersion": getattr(config, "config_version", None) or str(config.id),
            "status": config.status.value,
        },
    )
    return {"ok": True, "mapping": _serialize_config(config)}


@router.post("/{config_id}/reject")
async def reject_mapping_config(
    request: Request,
    config_id: str,
    payload: MappingReviewPayload,
):
    return await reject_mapping_config_action(request, config_id, payload)


@router.post("")
async def save_mapping_config(request: Request, config: MappingConfig):
    repo = _get_repo(request)
    query = {
        "partner": config.partner,
        "workflowType": config.workflow_type,
        "fileType": config.file_type.value,
        "status": MappingConfigStatus.APPROVED.value,
    }
    existing = await repo.find_one(query)
    config_dict = repo._to_mongo(config)
    
    # Generate dynamic version if it's missing or generic
    if not config.config_version or config.config_version in ("v_manual", "v_ai_generated", "latest"):
        config_dict["configVersion"] = await repo.allocate_next_version(config.partner)
        
    health = {
        "stale": False,
        "status": MappingConfigStatus.APPROVED.value,
        "approvedAt": datetime.now(timezone.utc),
        "confidence": 1.0,
        "reasoning": "Manually saved by administrator.",
    }
    config_dict["configHealth"] = health
    config_dict["status"] = MappingConfigStatus.APPROVED.value
    try:
        await invalidate_insight_cache(config.partner, date="")
    except Exception as cache_exc:
        logger.error(f"Failed to invalidate insight cache for {config.partner}: {cache_exc}")

    if existing:
        config_dict["_id"] = existing.id
        await repo.collection.replace_one({"_id": existing.id}, config_dict)
        return {"ok": True, "message": "Mapping config updated successfully.", "mapping": config_dict}
    await repo.collection.insert_one(config_dict)
    return {"ok": True, "message": "Mapping config created successfully.", "mapping": config_dict}


async def _create_mapping_proposal_from_source_file(
    request: Request,
    partner: str,
    source_file_path: Path,
    source_type: str = ReviewPacketSourceType.UPLOAD.value,
    source_file=None,
) -> dict:
    sig = compute_signature(source_file_path)
    if not sig.headers:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    config_dict, error = await generate_config_from_samples(
        partner=partner,
        headers=sig.headers,
        sample_rows=sig.sample_rows,
        known_constants={"provider": partner},
        header_row_index=sig.header_row_index,
        first_data_row_index=sig.first_data_row_index,
    )
    if error or config_dict is None:
        raise HTTPException(status_code=500, detail=f"AI mapping generation failed: {error}")

    field_mappings_raw = config_dict.get("fieldMappings") or []
    field_mappings_serialized, mapping_warnings = canonicalize_field_mappings(
        serialize_field_mappings(field_mappings_raw)
    )

    next_ver = await _get_repo(request).allocate_next_version(partner)
    proposal = MappingConfig(
        partner=partner,
        workflowType="UPC",
        fileType=FileType.SETTLEMENT,
        sheetName=config_dict.get("sheetName") or "Sheet1",
        startRow=config_dict.get("startRow") or 2,
        fieldMappings=field_mappings_serialized,
        configVersion=next_ver,
        structureSignature=sig.to_dict(),
        status=MappingConfigStatus.PENDING_APPROVAL,
        configHealth={
            "stale": False,
            "status": MappingConfigStatus.PENDING_APPROVAL.value,
            "confidence": config_dict.get("confidence") or 0.85,
            "reasoning": config_dict.get("reasoning") or "Automatically generated by AI.",
        },
    )
    await _get_repo(request).create(proposal)

    action = CopilotAction(
        type=CopilotActionType.MAPPING_PROPOSAL,
        status=CopilotActionStatus.PENDING_APPROVAL,
        partner=partner,
        workflowType="UPC",
        fileType=FileType.SETTLEMENT,
        draftMappingId=str(proposal.id),
        payload={
            "proposedMappings": field_mappings_serialized,
            "sheetName": proposal.sheet_name,
            "startRow": proposal.start_row,
            "confidence": config_dict.get("confidence") or 0.85,
            "reasoning": config_dict.get("reasoning") or "Automatically generated by AI.",
            "headers": sig.headers,
            "sampleRows": sig.sample_rows[:10],
        },
        reason="Generated from source file for review",
    )
    await _get_action_repo(request).create(action)
    active_runtime = await _get_repo(request).find_by_partner_and_type(
        partner, "UPC", FileType.SETTLEMENT
    )
    scope_meta = await classify_scope(
        _get_db(request),
        partner=partner,
        file_name=source_file_path.name,
        reconciliation_date=None,
    )
    validation_gates = [
        {
            "gateKey": "structure_signature",
            "label": "Structure signature generated",
            "status": "pass",
            "reason": "File headers and shape were fingerprinted successfully.",
        },
        {
            "gateKey": "required_fields",
            "label": "Required fields proposed",
            "status": "pass" if any(m.get("path") in {"id", "amount", "transDate"} for m in field_mappings_serialized) else "warn",
            "reason": "AI generated canonical fields for settlement parsing.",
        },
        {
            "gateKey": "runtime_impact",
            "label": "Runtime impact assessed",
            "status": "warn" if active_runtime else "warn",
            "reason": "Approved runtime config will be kept until reviewer decides." if active_runtime else "No approved runtime config exists yet.",
        },
    ]
    recommended_action_type = "APPROVE_AND_ACTIVATE_NEXT_RUNTIME" if active_runtime else "APPROVE_REQUIRED_BEFORE_RUNTIME"
    recommended_reason = (
        "Structure changed from the currently approved runtime; use the old runtime until review completes."
        if active_runtime
        else "No approved runtime config exists, so this draft must be reviewed before ingestion can continue."
    )
    packet = ReviewPacket(
        sourceType=ReviewPacketSourceType(source_type),
        partner=partner,
        fileName=source_file_path.name,
        fileTypeDetected=FileType.SETTLEMENT.value,
        structureSignature=proposal.structure_signature,
        activeRuntimeConfigId=str(active_runtime.id) if active_runtime else None,
        draftMappingId=str(proposal.id),
        targetActionId=str(action.id),
        sourceFileId=str(source_file.id) if source_file is not None else None,
        sourceFilePath=str(source_file_path),
        scopeType=scope_meta["scopeType"],
        scopeConfidence=scope_meta["scopeConfidence"],
        scopeReason=scope_meta["scopeReason"],
        scopeSignals=scope_meta["scopeSignals"],
        recommendedAction={
            "actionType": recommended_action_type,
            "reason": recommended_reason,
            "confidence": config_dict.get("confidence") or 0.85,
        },
        parseStrategy={
            "sheetName": proposal.sheet_name,
            "startRow": proposal.start_row,
            "fieldMappingCount": len(field_mappings_serialized),
            "strategy": "AI inferred spreadsheet draft mapping",
        },
        validationGates=validation_gates,
        samplePreview=[
            {"rowIndex": idx + 1, "values": row}
            for idx, row in enumerate(sig.sample_rows[:5])
        ],
        riskSummary={
            "severity": "high" if not active_runtime else "medium",
            "summary": recommended_reason,
        },
        runtimeDecisionHint=(
            "KEEP_CURRENT_RUNTIME_UNTIL_APPROVED" if active_runtime else "BLOCK_UNTIL_APPROVED"
        ),
    )
    await _get_review_packet_repo(request).create(packet)

    confidence_scores = {
        mapping["path"]: config_dict.get("confidence", 0.85)
        for mapping in field_mappings_serialized
        if mapping.get("path")
    }

    response_config = {
        "partner": partner,
        "workflowType": "UPC",
        "fileType": "SETTLEMENT",
        "sheetName": proposal.sheet_name,
        "startRow": proposal.start_row,
        "configVersion": proposal.config_version,
        "fieldMappings": field_mappings_serialized,
        "status": MappingConfigStatus.PENDING_APPROVAL.value,
        "configHealth": proposal.config_health,
    }
    return {
        "ok": True,
        "mapping": field_mappings_serialized,
        "confidenceScores": confidence_scores,
        "warnings": mapping_warnings,
        "suggestedConstants": [
            {"path": "currency", "constant": "VND", "reason": "Default settlement currency"}
        ],
        "config": response_config,
        "configStatus": MappingConfigStatus.PENDING_APPROVAL.value,
        "draftMappingId": str(proposal.id),
        "reviewItemId": str(packet.id),
        "isRuntimeEligible": False,
        "scopeAssessment": scope_meta,
        "planSummary": {
            "sheetName": proposal.sheet_name,
            "startRow": proposal.start_row,
            "fieldMappingCount": len(field_mappings_serialized),
        },
        "headers": sig.headers,
        "sampleRows": sig.sample_rows[:10],
    }


async def _create_mapping_proposal_from_upload(
    request: Request,
    partner: str,
    temp_file_path: Path,
) -> dict:
    return await _create_mapping_proposal_from_source_file(
        request=request,
        partner=partner,
        source_file_path=temp_file_path,
    )


if _MULTIPART_AVAILABLE:
    @router_v2.post("/ai-generate")
    async def ai_generate_mapping(
        request: Request,
        partner: str = Query(...),
        file: UploadFile = File(...),
    ):
        temp_dir = _get_upload_tmp_dir()
        temp_file_path = temp_dir / file.filename
        try:
            with open(temp_file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            return await _create_mapping_proposal_from_upload(request, partner, temp_file_path)
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Error generating config: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to generate config: {str(exc)}")
        finally:
            if temp_file_path.exists():
                temp_file_path.unlink()


@router_v2.post("/validate")
async def validate_mapping(payload: dict):
    raw_mappings = payload.get("fieldMappings", [])
    field_mappings, normalization_warnings = canonicalize_field_mappings(
        serialize_field_mappings(raw_mappings)
    )
    candidate_config = MappingConfig(
        partner=payload.get("partner") or "VALIDATION",
        workflowType=payload.get("workflowType") or "UPC",
        fileType=payload.get("fileType") or FileType.SETTLEMENT,
        sheetName=payload.get("sheetName") or "Sheet1",
        startRow=payload.get("startRow") or 2,
        fieldMappings=field_mappings,
        configVersion=payload.get("configVersion"),
    )
    validation = validate_mapping_contract(candidate_config)
    warnings = normalization_warnings + [
        warning for warning in validation.warnings if warning not in normalization_warnings
    ]
    return {
        "valid": validation.valid,
        "errors": validation.errors,
        "warnings": warnings,
        "score": validation.score,
        "scoreBreakdown": {
            "requiredFields": "Passed" if not validation.errors else "Failed",
            "warningsCount": len(warnings),
        },
    }


@router_v2.post("/test")
async def test_mapping(payload: dict):
    mapping_config = payload.get("mapping", {})
    sample_row = payload.get("sampleRow", [])
    output = {}
    mappings = mapping_config.get("fieldMappings", [])
    for mapping in mappings:
        path = mapping.get("path")
        if not path:
            continue
        val = None
        if mapping.get("type") == "CONSTANT":
            val = mapping.get("constant")
        elif "constant" in mapping and mapping["constant"] is not None:
            val = mapping["constant"]
        elif mapping.get("column") is not None:
            col_idx = int(mapping["column"]) - 1
            if 0 <= col_idx < len(sample_row):
                val = sample_row[col_idx]
        if val is not None and mapping.get("type", "STRING").upper() == "DECIMAL":
            try:
                val = float(val)
            except ValueError:
                pass
        if "." in path:
            curr = output
            parts = path.split(".")
            for part in parts[:-1]:
                curr = curr.setdefault(part, {})
            curr[parts[-1]] = val
        else:
            output[path] = val
    return {"ok": True, "output": output}


@router_v2.post("/publish")
async def publish_mapping(request: Request, config: MappingConfig):
    repo = _get_repo(request)
    config_dict = repo._to_mongo(config)
    health = {
        "stale": False,
        "status": MappingConfigStatus.APPROVED.value,
        "approvedAt": datetime.now(timezone.utc),
        "confidence": 1.0,
        "reasoning": "Published via Mapping Studio.",
    }
    config_dict["configHealth"] = health
    config_dict["status"] = MappingConfigStatus.APPROVED.value
    query = {
        "partner": config.partner,
        "workflowType": config.workflow_type,
        "fileType": config.file_type.value,
        "status": MappingConfigStatus.APPROVED.value,
    }
    existing = await repo.find_one(query)
    if existing:
        config_dict["_id"] = existing.id
        await repo.collection.replace_one({"_id": existing.id}, config_dict)
    else:
        await repo.collection.insert_one(config_dict)

    history_db = _get_db(request)["reconciliation_mapping_config_history"]
    history_doc = dict(config_dict)
    history_doc["_id"] = str(uuid4())
    history_doc["originalId"] = str(config_dict.get("_id"))
    history_doc["publishedAt"] = datetime.now(timezone.utc)
    await history_db.insert_one(history_doc)

    try:
        await invalidate_insight_cache(config.partner, date="")
    except Exception as cache_exc:
        logger.error(f"Failed to invalidate insight cache for {config.partner}: {cache_exc}")

    return {"ok": True, "message": "Schema published successfully.", "version": config.config_version}


@router_v2.get("/versions")
async def list_versions(request: Request, partner: str = Query(...)):
    history_db = _get_db(request)["reconciliation_mapping_config_history"]
    cursor = history_db.find({"partner": partner}).sort("publishedAt", -1)
    versions = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        if "publishedAt" in doc and isinstance(doc["publishedAt"], datetime):
            doc["publishedAt"] = doc["publishedAt"].isoformat()
        versions.append(doc)
    return {"versions": versions}


@router_v2.get("/version/{version_id}")
async def get_version(request: Request, version_id: str):
    history_db = _get_db(request)["reconciliation_mapping_config_history"]
    doc = await history_db.find_one({"_id": version_id})
    if doc is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    doc["_id"] = str(doc["_id"])
    if "publishedAt" in doc and isinstance(doc["publishedAt"], datetime):
        doc["publishedAt"] = doc["publishedAt"].isoformat()
    return doc


if _MULTIPART_AVAILABLE:
    @router.post("/generate")
    async def generate_mapping_config_from_file(
        request: Request,
        partner: str = Query(...),
        file: UploadFile = File(...),
    ):
        temp_dir = _get_upload_tmp_dir()
        temp_file_path = temp_dir / file.filename
        try:
            with open(temp_file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            result = await _create_mapping_proposal_from_upload(request, partner, temp_file_path)
            return {
                "ok": True,
                "config": result["config"],
                "draftMappingId": result["draftMappingId"],
                "reviewItemId": result.get("reviewItemId"),
            }
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Error generating config: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to generate config: {str(exc)}")
        finally:
            if temp_file_path.exists():
                temp_file_path.unlink()
