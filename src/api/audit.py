"""Audit log endpoints."""

from fastapi import APIRouter, HTTPException, Query, Request

from src.models.audit_event import AuditEventRepository

router = APIRouter(prefix="/api/v1/audit")


def _get_db(request: Request):
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available.")
    return db


def _serialize_event(event) -> dict:
    data = event.model_dump(by_alias=True)
    data["_id"] = str(data["_id"])
    if getattr(event, "created_at", None) is not None:
        data["createdAt"] = event.created_at.isoformat()
    return data

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
    query: dict = {}
    if entity_type:
        query["entityType"] = entity_type
    if entity_id:
        query["entityId"] = entity_id
    if action:
        query["action"] = action
    if partner:
        query["metadata.partner"] = partner
    if date:
        query["metadata.date"] = date

    db = _get_db(request)
    repo = AuditEventRepository(db)
    cursor = repo.collection.find(query).sort("createdAt", -1).limit(limit)
    events = []
    async for raw in cursor:
        events.append(_serialize_event(repo._from_mongo(raw)))
    return {"events": events, "limit": limit}
