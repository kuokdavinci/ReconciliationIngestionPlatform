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
from src.api.dependencies import get_request_db as _get_db
from src.api.query_validation import validate_partner as _validate_partner
from src.analysis.insights import invalidate_insight_cache
from src.config.ai_generator import generate_config_from_samples
from src.config.settings import settings
from src.config.signature import compute_signature
from src.core.enums import FileType
from src.infrastructure.review.repository import CopilotActionRepository
from src.domain.mapping.models import MappingConfig, MappingConfigStatus
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.domain.review.models import (
    ReviewPacketSourceType,
)
from src.infrastructure.review.repository import ReviewPacketRepository
from src.reconciliation.scope import classify_scope
from src.application.audit.service import record_audit_event
from src.application.mapping.errors import (
    MappingConflictError,
    MappingNotFoundError,
    MappingValidationError,
)
from src.application.mapping.proposals import (
    CreateMappingProposalCommand,
    MappingProposalService,
)
from src.application.mapping.service import (
    ApproveMappingCommand,
    MappingApplicationService,
    RejectMappingCommand,
    SaveMappingCommand,
)
from src.domain.mapping.contract import (
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


def _mapping_application_service(request: Request) -> MappingApplicationService:
    return MappingApplicationService(
        mapping_repo=_get_repo(request),
        action_repo=_get_action_repo(request),
        review_packet_repo=_get_review_packet_repo(request),
        audit_recorder=lambda **kwargs: record_audit_event(_get_db(request), **kwargs),
        cache_invalidator=invalidate_insight_cache,
    )


def _mapping_proposal_service(request: Request) -> MappingProposalService:
    async def classify(*, partner: str, reconciliation_date):
        return await classify_scope(
            _get_db(request),
            partner=partner,
            reconciliation_date=reconciliation_date,
        )

    return MappingProposalService(
        mapping_repo=_get_repo(request),
        action_repo=_get_action_repo(request),
        review_packet_repo=_get_review_packet_repo(request),
        signature_builder=compute_signature,
        config_generator=generate_config_from_samples,
        scope_classifier=classify,
    )


def _mapping_error(error: Exception) -> HTTPException:
    if isinstance(error, MappingNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, MappingConflictError):
        return HTTPException(status_code=400, detail=str(error))
    if isinstance(error, MappingValidationError):
        status = 500 if str(error).startswith("AI mapping generation failed") else 400
        return HTTPException(status_code=status, detail=str(error))
    return HTTPException(status_code=500, detail=str(error))


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
    try:
        result = await _mapping_application_service(request).approve(
            ApproveMappingCommand(
                config_id=config_id,
                actor=payload.reviewed_by,
                confidence=payload.confidence,
                reasoning=payload.reasoning,
            )
        )
        return {"ok": True, "mapping": _serialize_config(result.config)}
    except Exception as exc:
        raise _mapping_error(exc) from exc


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
    try:
        result = await _mapping_application_service(request).reject(
            RejectMappingCommand(config_id=config_id, actor=payload.reviewed_by)
        )
        return {"ok": True, "mapping": _serialize_config(result.config)}
    except Exception as exc:
        raise _mapping_error(exc) from exc


@router.post("/{config_id}/reject")
async def reject_mapping_config(
    request: Request,
    config_id: str,
    payload: MappingReviewPayload,
):
    return await reject_mapping_config_action(request, config_id, payload)


@router.post("")
async def save_mapping_config(request: Request, config: MappingConfig):
    try:
        result = await _mapping_application_service(request).save(
            SaveMappingCommand(config=config)
        )
        return {
            "ok": True,
            "message": result.message,
            "mapping": _serialize_config(result.config),
        }
    except Exception as exc:
        raise _mapping_error(exc) from exc


async def _create_mapping_proposal_from_source_file(
    request: Request,
    partner: str,
    source_file_path: Path,
    source_type: str = ReviewPacketSourceType.UPLOAD.value,
    source_file=None,
) -> dict:
    try:
        result = await _mapping_proposal_service(request).create_from_source_file(
            CreateMappingProposalCommand(
                partner=partner,
                source_file_path=source_file_path,
                source_type=source_type,
                source_file=source_file,
            )
        )
        return result.response
    except MappingValidationError as exc:
        status_code = 500 if str(exc).startswith("AI mapping generation failed") else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

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
