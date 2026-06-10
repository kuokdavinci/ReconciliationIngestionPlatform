"""Operational intake and approval overview endpoints."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from src.models.copilot_action import CopilotActionRepository
from src.models.mapping_config import MappingConfigRepository
from src.models.reconciliation_file import ReconciliationFileRepository
from src.models.review_packet import ReviewPacketRepository

router = APIRouter(prefix="/api/v1/operations")


def _enum_value(value):
    return getattr(value, "value", value)


def _get_db(request: Request):
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available.")
    return db


def _serialize_mapping(config) -> dict:
    data = config.model_dump(by_alias=True)
    data["_id"] = str(data["_id"])
    if data.get("fileType") is not None:
        data["fileType"] = str(data["fileType"])
    return data


def _serialize_action(action) -> dict:
    data = action.model_dump(by_alias=True)
    data["_id"] = str(data["_id"])
    if data.get("fileType") is not None:
        data["fileType"] = str(data["fileType"])
    return data


def _serialize_file(record) -> dict:
    data = record.model_dump(by_alias=True)
    data["_id"] = str(data["_id"])
    if data.get("fileType") is not None:
        data["fileType"] = str(data["fileType"])
    return data


def _serialize_packet(packet) -> dict:
    data = packet.model_dump(by_alias=True)
    data["_id"] = str(data["_id"])
    return data


def _compute_partner_state(approved_config, pending_proposals, pending_actions, latest_file):
    if approved_config is None and (pending_proposals or pending_actions):
        return "BLOCKED", "No approved runtime config", "Create or review a draft mapping in Review Center"
    if pending_proposals or pending_actions:
        return "NEEDS_REVIEW", "Pending review items require attention", "Review pending items in Review Center"
    if approved_config is not None:
        if latest_file is not None:
            return "ACTIVE", "Approved runtime config is available", "Monitor latest file processing"
        return "ACTIVE", "Approved runtime config is available", "Submit sample when partner format changes"
    return "NO_ACTIVITY", "No files or runtime config yet", "Submit a partner sample to start onboarding"


def _build_activity_items(files, mappings, actions, packets):
    activity = []
    for file in files:
        activity.append(
            {
                "kind": "FILE",
                "timestamp": file.get("uploadedAt") or file.get("createdAt") or file.get("reconciliationDate"),
                "title": file.get("fileName") or "Partner file received",
                "status": file.get("processingStatus"),
                "detail": f"{file.get('fileType', '-')}"
            }
        )
    for mapping in mappings:
        activity.append(
            {
                "kind": "CONFIG",
                "timestamp": mapping.get("approvedAt") or mapping.get("createdAt"),
                "title": f"Config {mapping.get('configVersion') or 'latest'}",
                "status": mapping.get("status"),
                "detail": mapping.get("configHealth", {}).get("reasoning") or mapping.get("sheetName") or "-"
            }
        )
    for action in actions:
        activity.append(
            {
                "kind": "ACTION",
                "timestamp": action.get("reviewedAt") or action.get("createdAt"),
                "title": action.get("type") or "Copilot recommendation",
                "status": action.get("status"),
                "detail": action.get("reason") or "-"
            }
        )
    for packet in packets:
        activity.append(
            {
                "kind": "REVIEW",
                "timestamp": packet.get("reviewedAt") or packet.get("createdAt"),
                "title": packet.get("fileName") or "Review item",
                "status": packet.get("status"),
                "detail": packet.get("recommendedAction", {}).get("reason") or packet.get("riskSummary", {}).get("summary") or "-",
            }
        )
    activity.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
    return activity


@router.get("/intake")
async def get_partner_intake(
    request: Request,
    partner: Optional[str] = Query(default=None),
    date: Optional[str] = Query(default=None),
):
    db = _get_db(request)
    mapping_repo = MappingConfigRepository(db)
    action_repo = CopilotActionRepository(db)
    file_repo = ReconciliationFileRepository(db)
    packet_repo = ReviewPacketRepository(db)

    file_query: dict = {}
    if partner:
        file_query["partner"] = partner
    if date:
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Expected YYYY-MM-DD.")
        start = dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
        end = dt.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc)
        file_query["reconciliationDate"] = {"$gte": start, "$lte": end}

    mappings_query: dict = {}
    actions_query: dict = {}
    if partner:
        mappings_query["partner"] = partner
        actions_query["partner"] = partner

    files = await file_repo.find_many(file_query)
    mappings = await mapping_repo.find_many(mappings_query)
    actions = await action_repo.find_many(actions_query)
    packets = await packet_repo.find_many(actions_query)

    partners = sorted({*[f.partner for f in files], *[m.partner for m in mappings], *[a.partner for a in actions], *[p.partner for p in packets]})
    if partner and partner not in partners:
        partners.append(partner)

    summaries = []
    for partner_name in partners:
        partner_files = [f for f in files if f.partner == partner_name]
        partner_mappings = [m for m in mappings if m.partner == partner_name]
        partner_actions = [a for a in actions if a.partner == partner_name]
        partner_packets = [p for p in packets if p.partner == partner_name]
        approved = next((m for m in partner_mappings if _enum_value(m.status) == "APPROVED"), None)
        pending_proposals = [m for m in partner_mappings if _enum_value(m.status) == "PENDING_APPROVAL"]
        pending_actions = [a for a in partner_actions if _enum_value(a.status) == "PENDING_APPROVAL"]
        pending_packets = [p for p in partner_packets if _enum_value(p.status) == "PENDING"]
        latest_file = max(partner_files, key=lambda f: f.uploaded_at or f.created_at, default=None)
        overall_state, primary_reason, next_action = _compute_partner_state(
            approved, pending_proposals, pending_packets or pending_actions, latest_file
        )
        summaries.append(
            {
                "partner": partner_name,
                "overallState": overall_state,
                "primaryReason": primary_reason,
                "nextAction": next_action,
                "currentApprovedConfig": _serialize_mapping(approved) if approved else None,
                "pendingProposalCount": len(pending_proposals),
                "pendingActionCount": len(pending_packets or pending_actions),
                "latestFileSummary": _serialize_file(latest_file) if latest_file else None,
                "fileCount": len(partner_files),
            }
        )

    selected_partner = partner or (summaries[0]["partner"] if summaries else None)
    detail = None
    if selected_partner:
        detail_files = [
            _serialize_file(f)
            for f in sorted([f for f in files if f.partner == selected_partner], key=lambda f: f.uploaded_at or f.created_at, reverse=True)
        ]
        detail_mappings = [
            _serialize_mapping(m)
            for m in sorted([m for m in mappings if m.partner == selected_partner], key=lambda m: m.created_at, reverse=True)
        ]
        detail_actions = [
            _serialize_action(a)
            for a in sorted([a for a in actions if a.partner == selected_partner], key=lambda a: a.created_at, reverse=True)
        ]
        detail_packets = [
            _serialize_packet(p)
            for p in sorted([p for p in packets if p.partner == selected_partner], key=lambda p: p.created_at, reverse=True)
        ]
        current_approved = next((m for m in detail_mappings if m.get("status") == "APPROVED"), None)
        pending_items = [
            {
                "kind": "REVIEW_PACKET",
                "title": item.get("recommendedAction", {}).get("actionType") or "Pending review item",
                "reason": item.get("recommendedAction", {}).get("reason") or item.get("riskSummary", {}).get("summary") or "-",
                "draftMappingId": item.get("draftMappingId"),
                "reviewItemId": item.get("_id"),
                "fileName": item.get("fileName"),
                "status": item.get("status"),
                "createdAt": item.get("createdAt"),
            }
            for item in detail_packets
            if item.get("status") == "PENDING"
        ]
        covered_config_ids = {
            item.get("draftMappingId")
            for item in detail_packets
            if item.get("status") == "PENDING"
        }
        for m in detail_mappings:
            if m.get("status") == "PENDING_APPROVAL" and m.get("_id") not in covered_config_ids:
                pending_items.append({
                    "kind": "MAPPING_CONFIG",
                    "title": "Pending Draft Mapping",
                    "reason": m.get("configHealth", {}).get("reasoning") or "AI generated draft mapping awaits approval.",
                    "draftMappingId": m.get("_id"),
                    "reviewItemId": None,
                    "fileName": m.get("sheetName") or "Default Sheet",
                    "status": m.get("status"),
                    "createdAt": m.get("createdAt"),
                })
        latest_file = detail_files[0] if detail_files else None
        overall_state, primary_reason, next_action = _compute_partner_state(
            current_approved,
            [m for m in detail_mappings if m.get("status") == "PENDING_APPROVAL"],
            [p for p in detail_packets if p.get("status") == "PENDING"],
            latest_file,
        )
        detail = {
            "partner": selected_partner,
            "statusHeader": {
                "overallState": overall_state,
                "primaryReason": primary_reason,
                "nextAction": next_action,
            },
            "currentRuntimeConfigSummary": {
                "configVersion": current_approved.get("configVersion") if current_approved else None,
                "sheetName": current_approved.get("sheetName") if current_approved else None,
                "startRow": current_approved.get("startRow") if current_approved else None,
                "approvedAt": current_approved.get("approvedAt") if current_approved else None,
            },
            "latestFileSummary": latest_file,
            "pendingItems": pending_items,
            "reviewPackets": detail_packets[:12],
            "recentActivity": _build_activity_items(detail_files, detail_mappings, detail_actions, detail_packets)[:12],
        }

    return {
        "partners": summaries,
        "selectedPartner": selected_partner,
        "detail": detail,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
