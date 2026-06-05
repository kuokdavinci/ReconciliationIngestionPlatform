"""FastAPI router for copilot approval actions."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from src.models.copilot_action import CopilotActionRepository, CopilotActionStatus

router = APIRouter(prefix="/api/v1/copilot")


def _get_repo(request: Request) -> CopilotActionRepository:
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available.")
    return CopilotActionRepository(db)


def _serialize(action) -> dict:
    data = action.model_dump(by_alias=True)
    data["_id"] = str(data["_id"])
    if data.get("fileType") is not None:
        data["fileType"] = str(data["fileType"])
    return data


@router.get("/actions")
async def list_actions(
    request: Request,
    status: Optional[str] = Query(default=None),
    partner: Optional[str] = Query(default=None),
):
    repo = _get_repo(request)
    query: dict = {}
    if status:
        query["status"] = status
    if partner:
        query["partner"] = partner
    actions = await repo.find_many(query)
    return {"actions": [_serialize(action) for action in actions]}


async def _review_action(request: Request, action_id: str, status: CopilotActionStatus):
    repo = _get_repo(request)
    action = await repo.find_one({"_id": action_id})
    if action is None:
        raise HTTPException(status_code=404, detail="Copilot action not found.")
    now = datetime.now(timezone.utc)
    await repo.collection.update_one(
        {"_id": action_id},
        {"$set": {"status": status.value, "reviewedAt": now}},
    )
    action.status = status
    action.reviewed_at = now
    return {"ok": True, "action": _serialize(action)}


@router.post("/actions/{action_id}/approve")
async def approve_action(request: Request, action_id: str):
    return await _review_action(request, action_id, CopilotActionStatus.APPROVED)


@router.post("/actions/{action_id}/reject")
async def reject_action(request: Request, action_id: str):
    return await _review_action(request, action_id, CopilotActionStatus.REJECTED)
