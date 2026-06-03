"""FastAPI Router for mapping configuration endpoints.

Provides:
- GET /api/v1/mappings — list active mapping configurations
- POST /api/v1/mappings/{id}/approve — mark AI-generated config as ACTIVE
"""

import logging
import shutil
from pathlib import Path
from typing import Optional

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request, File, UploadFile
from pydantic import BaseModel

from src.models.mapping_config import MappingConfig, MappingConfigRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/mappings")


def _validate_partner(partner: Optional[str]) -> Optional[str]:
    """Validate optional partner identifier."""
    if partner is not None and not partner.strip():
        raise HTTPException(
            status_code=400,
            detail="Partner identifier cannot be empty.",
        )
    return partner.strip() if partner else None


def _get_repo(request: Request) -> MappingConfigRepository:
    """Get MappingConfigRepository from app state DB."""
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection not available.",
        )
    try:
        return MappingConfigRepository(db)
    except Exception as exc:
        logger.error(f"Failed to create repository: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Failed to initialize repository.",
        )


def _serialize_config(obj: MappingConfig) -> dict:
    """Serialize MappingConfig for API response."""
    d = obj.model_dump(by_alias=True)
    # Convert UUID/ObjectId _id to string
    if "_id" in d:
        d["_id"] = str(d["_id"])
    return d


class ApproveMappingConfigPayload(BaseModel):
    confidence: float | None = None
    reasoning: str | None = None


@router.get("")
async def list_mappings(
    request: Request,
    partner: Optional[str] = Query(default=None, description="Partner identifier (optional)"),
):
    """List active mapping configurations.

    If partner is provided, filters configs by that partner.
    Otherwise returns all configurations.

    Returns:
        List of mapping config objects with field mapping details.
    """
    try:
        partner = _validate_partner(partner)
    except HTTPException:
        raise

    try:
        repo = _get_repo(request)
        query: dict = {}
        if partner:
            query["partner"] = partner

        records = await repo.find_many(query)
        return {"mappings": [_serialize_config(r) for r in records]}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error listing mappings: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list mappings: {str(exc)}",
        )


@router.post("/{config_id}/approve")
async def approve_mapping_config(request: Request, config_id: str, payload: ApproveMappingConfigPayload):
    """Approve a pending mapping config and mark it ACTIVE."""
    repo = _get_repo(request)
    config = await repo.find_one({"_id": config_id})
    if config is None:
        raise HTTPException(status_code=404, detail="Mapping config not found.")

    health = dict(config.config_health or {})
    health.update({
        "stale": False,
        "status": "ACTIVE",
        "approvedAt": datetime.now(timezone.utc),
    })
    if payload.confidence is not None:
        health["confidence"] = payload.confidence
    if payload.reasoning is not None:
        health["reasoning"] = payload.reasoning

    await repo.collection.update_one(
        {"_id": config_id},
        {"$set": {"configHealth": health}},
    )
    config.config_health = health
    return {"ok": True, "mapping": _serialize_config(config)}


@router.post("")
async def save_mapping_config(request: Request, config: MappingConfig):
    """Save (create or replace) a mapping configuration."""
    repo = _get_repo(request)
    
    query = {
        "partner": config.partner,
        "workflowType": config.workflow_type,
        "fileType": config.file_type.value
    }
    
    existing = await repo.find_one(query)
    config_dict = repo._to_mongo(config)
    
    health = {
        "stale": False,
        "status": "ACTIVE",
        "approvedAt": datetime.now(timezone.utc),
        "confidence": 1.0,
        "reasoning": "Manually saved by administrator."
    }
    config_dict["configHealth"] = health
    
    if existing:
        config_dict["_id"] = existing.id
        await repo.collection.replace_one({"_id": existing.id}, config_dict)
        return {"ok": True, "message": "Mapping config updated successfully.", "mapping": config_dict}
    else:
        await repo.collection.insert_one(config_dict)
        return {"ok": True, "message": "Mapping config created successfully.", "mapping": config_dict}


router_v2 = APIRouter(prefix="/api/v1/mapping")


@router_v2.post("/ai-generate")
async def ai_generate_mapping(
    request: Request,
    partner: str = Query(..., description="Partner identifier"),
    file: UploadFile = File(...),
):
    """Generate mapping configuration from uploaded sample file using AI."""
    temp_dir = Path("/home/kuokdavinci/AdapterService/scratch/temp_uploads")
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    temp_file_path = temp_dir / file.filename
    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        from src.config.signature import read_raw_rows
        from src.config.ai_generator import generate_config_from_samples
        
        raw_rows = read_raw_rows(temp_file_path, max_rows=15)
        if not raw_rows:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
            
        headers = raw_rows[0]
        sample_rows = raw_rows[1:]
        
        config_dict, error = await generate_config_from_samples(
            partner=partner,
            headers=headers,
            sample_rows=sample_rows,
            known_constants={"provider": partner}
        )
        
        if error or config_dict is None:
            raise HTTPException(status_code=500, detail=f"AI mapping generation failed: {error}")

        field_mappings_raw = config_dict.get("fieldMappings") or []
        field_mappings_serialized = []
        for fm in field_mappings_raw:
            if hasattr(fm, "model_dump"):
                field_mappings_serialized.append(fm.model_dump(by_alias=True))
            else:
                field_mappings_serialized.append(fm)
            
        response_config = {
            "partner": partner,
            "workflowType": "UPC",
            "fileType": "SETTLEMENT",
            "sheetName": config_dict.get("sheetName") or "Sheet1",
            "startRow": config_dict.get("startRow") or 2,
            "configVersion": "v_ai_generated",
            "fieldMappings": field_mappings_serialized,
            "configHealth": {
                "stale": False,
                "status": "PENDING_REVIEW",
                "confidence": config_dict.get("confidence") or 0.85,
                "reasoning": config_dict.get("reasoning") or "Automatically generated by AI."
            }
        }
        
        confidence_scores = {}
        for fm in field_mappings_serialized:
            confidence_scores[fm["path"]] = config_dict.get("confidence", 0.85)
            
        return {
            "ok": True,
            "mapping": response_config["fieldMappings"],
            "confidence_scores": confidence_scores,
            "warnings": [],
            "suggested_constants": [
                {"path": "currency", "constant": "VND", "reason": "Default settlement currency"}
            ],
            "config": response_config,
            "headers": headers,
            "sample_rows": sample_rows[:10]
        }
        
    except Exception as exc:
        logger.error(f"Error generating config: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate config: {str(exc)}")
    finally:
        if temp_file_path.exists():
            temp_file_path.unlink()


@router_v2.post("/validate")
async def validate_mapping(payload: dict):
    errors = []
    warnings = []
    
    mappings = payload.get("fieldMappings", [])
    mapped_paths = {m.get("path") for m in mappings if m.get("path")}
    
    if not ("id" in mapped_paths or "transaction_id" in mapped_paths):
        errors.append("Missing required field mapping: transaction_id (or id)")
    if "amount" not in mapped_paths:
        errors.append("Missing required field mapping: amount")
    if not ("transDate" in mapped_paths or "transaction_time" in mapped_paths):
        errors.append("Missing required field mapping: transaction_time (or transDate)")
        
    source_cols = {}
    for m in mappings:
        col = m.get("column")
        if col is not None:
            if col in source_cols:
                source_cols[col].append(m.get("path"))
            else:
                source_cols[col] = [m.get("path")]
                
    for col, paths in source_cols.items():
        if len(paths) > 1:
            warnings.append(f"Column {col} is mapped to multiple fields: {', '.join(paths)}")
            
    for m in mappings:
        if m.get("column") is None and m.get("constant") is None:
            warnings.append(f"Field '{m.get('path')}' has neither a source column nor a constant value.")
            
    score = 100
    if errors:
        score -= len(errors) * 15
    if warnings:
        score -= len(warnings) * 5
        
    score = max(0, min(100, score))
    
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "score": score,
        "score_breakdown": {
            "required_fields": "Passed" if not errors else "Failed",
            "warnings_count": len(warnings)
        }
    }


@router_v2.post("/test")
async def test_mapping(payload: dict):
    mapping_config = payload.get("mapping", {})
    sample_row = payload.get("sampleRow", [])
    
    output = {}
    mappings = mapping_config.get("fieldMappings", [])
    
    for m in mappings:
        path = m.get("path")
        if not path:
            continue
            
        val = None
        if m.get("type") == "CONSTANT":
            val = m.get("constant")
        elif "constant" in m and m["constant"] is not None:
            val = m["constant"]
        elif m.get("column") is not None:
            col_idx = int(m["column"]) - 1
            if 0 <= col_idx < len(sample_row):
                val = sample_row[col_idx]
                
        if val is not None:
            m_type = m.get("type", "STRING").upper()
            if m_type == "DECIMAL":
                try:
                    val = float(val)
                except ValueError:
                    pass
                    
        if "." in path:
            parts = path.split(".")
            curr = output
            for part in parts[:-1]:
                if part not in curr:
                    curr[part] = {}
                curr = curr[part]
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
        "status": "ACTIVE",
        "approvedAt": datetime.now(timezone.utc),
        "confidence": 1.0,
        "reasoning": "Published via Mapping Studio."
    }
    config_dict["configHealth"] = health
    
    query = {
        "partner": config.partner,
        "workflowType": config.workflow_type,
        "fileType": config.file_type.value
    }
    existing = await repo.find_one(query)
    
    if existing:
        config_dict["_id"] = existing.id
        await repo.collection.replace_one({"_id": existing.id}, config_dict)
    else:
        await repo.collection.insert_one(config_dict)
        
    history_db = request.app.state.db["reconciliation_mapping_config_history"]
    history_doc = dict(config_dict)
    from uuid import uuid4
    history_doc["_id"] = str(uuid4())
    history_doc["originalId"] = str(config_dict.get("_id"))
    history_doc["publishedAt"] = datetime.now(timezone.utc)
    await history_db.insert_one(history_doc)
    
    return {"ok": True, "message": "Schema published successfully.", "version": config.config_version}


@router_v2.get("/versions")
async def list_versions(request: Request, partner: str = Query(..., description="Partner name")):
    history_db = request.app.state.db["reconciliation_mapping_config_history"]
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
    history_db = request.app.state.db["reconciliation_mapping_config_history"]
    doc = await history_db.find_one({"_id": version_id})
    if doc is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    doc["_id"] = str(doc["_id"])
    if "publishedAt" in doc and isinstance(doc["publishedAt"], datetime):
        doc["publishedAt"] = doc["publishedAt"].isoformat()
    return doc


@router.post("/generate")
async def generate_mapping_config_from_file(
    request: Request,
    partner: str = Query(..., description="Partner identifier"),
    file: UploadFile = File(...),
):
    """Generate mapping configuration from uploaded sample file using AI."""
    temp_dir = Path("/home/kuokdavinci/AdapterService/scratch/temp_uploads")
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    temp_file_path = temp_dir / file.filename
    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        from src.config.signature import read_raw_rows
        from src.config.ai_generator import generate_config_from_samples
        
        raw_rows = read_raw_rows(temp_file_path, max_rows=15)
        if not raw_rows:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
            
        headers = raw_rows[0]
        sample_rows = raw_rows[1:]
        
        config_dict, error = await generate_config_from_samples(
            partner=partner,
            headers=headers,
            sample_rows=sample_rows,
            known_constants={"provider": partner}
        )
        
        if error or config_dict is None:
            raise HTTPException(status_code=500, detail=f"AI mapping generation failed: {error}")
            
        field_mappings_raw = config_dict.get("fieldMappings") or []
        field_mappings_serialized = []
        for fm in field_mappings_raw:
            if hasattr(fm, "model_dump"):
                field_mappings_serialized.append(fm.model_dump(by_alias=True))
            else:
                field_mappings_serialized.append(fm)
            
        response_config = {
            "partner": partner,
            "workflowType": "UPC",
            "fileType": "SETTLEMENT",
            "sheetName": config_dict.get("sheetName") or "Sheet1",
            "startRow": config_dict.get("startRow") or 2,
            "configVersion": "v_ai_generated",
            "fieldMappings": field_mappings_serialized,
            "configHealth": {
                "stale": False,
                "status": "PENDING_REVIEW",
                "confidence": config_dict.get("confidence") or 0.85,
                "reasoning": config_dict.get("reasoning") or "Automatically generated by AI."
            }
        }
        return {"ok": True, "config": response_config}
        
    except Exception as exc:
        logger.error(f"Error generating config: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate config: {str(exc)}")
    finally:
        if temp_file_path.exists():
            temp_file_path.unlink()
