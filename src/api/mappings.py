"""FastAPI Router for mapping configuration endpoints.

Provides:
- GET /api/v1/mappings — list active mapping configurations
- POST /api/v1/mappings/{id}/approve — mark AI-generated config as ACTIVE
"""

import logging
from typing import Optional

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
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
