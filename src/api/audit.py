"""Audit log endpoints."""

from fastapi import APIRouter, Query, Request

from src.api.dependencies import get_request_db as _get_db
from src.infrastructure.audit.repository import AuditEventRepository

router = APIRouter(prefix="/api/v1/audit")
DATE_OPTIONAL_ENTITY_TYPES = {"MAPPING_CONFIG"}


def _serialize_event(event) -> dict:
    data = event.model_dump(by_alias=True)
    data["_id"] = str(data["_id"])
    if getattr(event, "created_at", None) is not None:
        data["createdAt"] = event.created_at.isoformat()
    return data


def _build_audit_query(
    *,
    entity_type: str | None,
    entity_id: str | None,
    partner: str | None,
    date: str | None,
    action: str | None,
) -> dict:
    query: dict = {}
    if entity_type:
        query["entityType"] = entity_type
    if entity_id:
        query["entityId"] = entity_id
    if action:
        query["action"] = action
    if partner:
        query["metadata.partner"] = partner
    if not date:
        return query

    if entity_type in DATE_OPTIONAL_ENTITY_TYPES:
        return query

    if entity_type is None:
        query["$or"] = [
            {"metadata.date": date},
            {
                "entityType": {"$in": sorted(DATE_OPTIONAL_ENTITY_TYPES)},
                "metadata.date": {"$exists": False},
            },
        ]
        return query

    query["metadata.date"] = date
    return query

@router.get("/events")
async def list_audit_events(
    request: Request,
    entity_type: str | None = Query(default=None, alias="entityType"),
    entity_id: str | None = Query(default=None, alias="entityId"),
    partner: str | None = Query(default=None),
    date: str | None = Query(default=None),
    action: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    query = _build_audit_query(
        entity_type=entity_type,
        entity_id=entity_id,
        partner=partner,
        date=date,
        action=action,
    )
    db = _get_db(request)
    repo = AuditEventRepository(db)
    cursor = repo.collection.find(query).sort("createdAt", -1).limit(limit)
    events = []
    async for raw in cursor:
        events.append(_serialize_event(repo._from_mongo(raw)))
    return {"events": events, "limit": limit}
