"""FastAPI router for embedded Copilot dashboard context."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.api.actor import require_actor
from src.api.dependencies import get_request_db as _get_db
from src.api.mappings import (
    MappingReviewPayload,
    approve_mapping_config_action,
    reject_mapping_config_action,
)
from src.api.review_packets import (
    ReviewDecisionPayload,
    approve_activate_packet_action,
    approve_keep_current_packet_action,
    reject_packet_action,
)
from src.domain.review.models import CopilotActionStatus
from src.infrastructure.review.repository import CopilotActionRepository
from src.application.copilot.context import CopilotContextService
from src.application.review.errors import (
    ReviewError,
    ReviewNotFoundError,
    ReviewValidationError,
)

router = APIRouter(prefix="/api/v1/copilot")


async def _copilot_context(service: CopilotContextService, **values):
    try:
        return await service.context(**values)
    except ReviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReviewValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ReviewError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _copilot_resolution(service: CopilotContextService, **values):
    try:
        return await service.resolve(**values)
    except ReviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReviewValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ReviewError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class CopilotActionPayload(BaseModel):
    partner: Optional[str] = None
    date: Optional[str] = None
    file_id: Optional[str] = Field(default=None, alias="fileId")
    reviewed_by: Optional[str] = Field(default=None, alias="reviewedBy")
    scope_type: Optional[str] = Field(default=None, alias="scopeType")


def _get_repo(request: Request) -> CopilotActionRepository:
    return CopilotActionRepository(_get_db(request))


def _serialize(action) -> dict:
    data = action.model_dump(by_alias=True)
    data["_id"] = str(data["_id"])
    if data.get("fileType") is not None:
        data["fileType"] = str(data["fileType"])
    return data


@router.get("/context")
async def get_context(
    request: Request,
    partner: str = Query(...),
    date: Optional[str] = Query(default=None),
    screen: Optional[str] = Query(default=None),
):
    return await _copilot_context(
        CopilotContextService(_get_db(request)),
        partner=partner,
        date=date,
        screen=screen,
    )


@router.get("/context/file/{file_id}")
async def get_file_context(
    request: Request,
    file_id: str,
    partner: str = Query(...),
    screen: Optional[str] = Query(default=None),
):
    return await _copilot_context(
        CopilotContextService(_get_db(request)),
        partner=partner,
        file_id=file_id,
        screen=screen,
    )


@router.post("/actions/{action_key}")
async def execute_copilot_action(
    request: Request,
    action_key: str,
    payload: CopilotActionPayload,
):
    partner = payload.partner
    if not partner:
        raise HTTPException(status_code=400, detail="Partner is required for Copilot actions.")

    service = CopilotContextService(_get_db(request))
    resolution = await _copilot_resolution(
        service,
        partner=partner,
        date=payload.date,
        file_id=payload.file_id,
    )
    refs = resolution.refs
    review_item_id = refs.get("reviewItemId")
    draft_mapping_id = refs.get("draftMappingId")

    if action_key == "refresh_context":
        return {"ok": True, "context": resolution.context}

    if action_key == "review_proposal":
        target = {"type": "review_queue", "partner": partner}
        if review_item_id:
            target.update({"type": "review_drawer", "reviewItemId": review_item_id})
        return {"ok": True, "target": target, "context": resolution.context}

    if action_key == "open_mapping_details":
        target = {"type": "mapping_studio", "partner": partner}
        if review_item_id:
            target["reviewItemId"] = review_item_id
        if draft_mapping_id:
            target["draftMappingId"] = draft_mapping_id
        return {"ok": True, "target": target, "context": resolution.context}

    if action_key == "approve_keep_current":
        payload.reviewed_by = require_actor(request, payload_actor=payload.reviewed_by)
        if not review_item_id:
            raise HTTPException(status_code=400, detail="No review packet is available for this action.")
        result = await approve_keep_current_packet_action(
            request,
            review_item_id,
            ReviewDecisionPayload(reviewedBy=payload.reviewed_by, scopeType=payload.scope_type),
        )
        context = await _copilot_context(
            service,
            partner=partner,
            date=payload.date,
            file_id=payload.file_id,
        )
        return {"ok": True, "result": result, "context": context}

    if action_key == "approve_activate_next_runtime":
        payload.reviewed_by = require_actor(request, payload_actor=payload.reviewed_by)
        if review_item_id:
            result = await approve_activate_packet_action(
                request,
                review_item_id,
                ReviewDecisionPayload(reviewedBy=payload.reviewed_by, scopeType=payload.scope_type),
            )
        elif draft_mapping_id:
            result = await approve_mapping_config_action(
                request,
                draft_mapping_id,
                MappingReviewPayload(reviewedBy=payload.reviewed_by),
            )
        else:
            raise HTTPException(status_code=400, detail="No proposal is available for this action.")
        context = await _copilot_context(
            service,
            partner=partner,
            date=payload.date,
            file_id=payload.file_id,
        )
        return {"ok": True, "result": result, "context": context}

    if action_key == "reject_proposal":
        payload.reviewed_by = require_actor(request, payload_actor=payload.reviewed_by)
        if review_item_id:
            result = await reject_packet_action(
                request,
                review_item_id,
                ReviewDecisionPayload(reviewedBy=payload.reviewed_by),
            )
        elif draft_mapping_id:
            result = await reject_mapping_config_action(
                request,
                draft_mapping_id,
                MappingReviewPayload(reviewedBy=payload.reviewed_by),
            )
        else:
            raise HTTPException(status_code=400, detail="No proposal is available for this action.")
        context = await _copilot_context(
            service,
            partner=partner,
            date=payload.date,
            file_id=payload.file_id,
        )
        return {"ok": True, "result": result, "context": context}

    raise HTTPException(status_code=404, detail=f"Unsupported Copilot action: {action_key}")


@router.get("/actions")
async def list_actions(
    request: Request,
    status: Optional[str] = Query(default=None),
    partner: Optional[str] = Query(default=None),
):
    """Compatibility endpoint for legacy approval clients."""

    repo = _get_repo(request)
    query: dict = {}
    if status:
        query["status"] = status
    if partner:
        query["partner"] = partner
    actions = await repo.find_many(query)
    return {"actions": [_serialize(action) for action in actions]}


async def _review_action(request: Request, action_id: str, status: CopilotActionStatus):
    actor = require_actor(request, payload_field_name="actor")
    repo = _get_repo(request)
    action = await repo.find_one({"_id": action_id})
    if action is None:
        raise HTTPException(status_code=404, detail="Copilot action not found.")
    now = datetime.now(timezone.utc)
    await repo.collection.update_one(
        {"_id": action_id},
        {"$set": {"status": status.value, "reviewedAt": now, "reviewedBy": actor}},
    )
    action.status = status
    action.reviewed_at = now
    action.reviewed_by = actor
    return {"ok": True, "action": _serialize(action)}


@router.post("/actions/{action_id}/approve")
async def approve_action(request: Request, action_id: str):
    return await _review_action(request, action_id, CopilotActionStatus.APPROVED)


@router.post("/actions/{action_id}/reject")
async def reject_action(request: Request, action_id: str):
    return await _review_action(request, action_id, CopilotActionStatus.REJECTED)
