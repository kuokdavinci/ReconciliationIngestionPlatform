"""Approval desk review packet endpoints."""

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api.actor import require_actor
from src.config.ai_generator import generate_config_from_samples
from src.core.enums import FileType
from src.domain.mapping.models import MappingConfig, MappingConfigStatus
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.infrastructure.partner_transaction.repository import DataContainerRepository
from src.infrastructure.review.repository import PostApprovalRunRepository
from src.domain.review.models import (
    ReviewPacket,
    ReviewDecisionMode,
    ReviewPacketSourceType,
    ReviewPacketStatus,
)
from src.infrastructure.review.repository import ReviewPacketRepository
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
_SCOPE_LLM_TIMEOUT_SECONDS = 8.0


def _normalized_filename_tokens(file_name: str) -> str:
    return str(file_name or "").strip().lower()


def _scope_probabilities(
    *,
    file_name: str,
    internal_count: int,
    received_count: int,
) -> tuple[dict[str, float], str, str]:
    lowered = _normalized_filename_tokens(file_name)
    replacement_tokens = ("replace", "replacement", "rerun", "retry", "resend", "correct", "correction")
    incremental_tokens = ("part", "batch", "delta", "append", "supplement", "wave")
    snapshot_tokens = ("full", "final", "daily", "settlement")

    if any(token in lowered for token in replacement_tokens):
        return (
            {"FULL_SNAPSHOT": 0.08, "INCREMENTAL_APPEND": 0.12, "REPLACEMENT": 0.8},
            "REPLACEMENT",
            "Filename contains replacement/correction hints, so this file is most likely intended to overwrite existing rows.",
        )

    if received_count <= 0:
        return (
            {"FULL_SNAPSHOT": 0.34, "INCREMENTAL_APPEND": 0.33, "REPLACEMENT": 0.33},
            "FULL_SNAPSHOT",
            "No reliable row-count signal was available, so the suggestion stays conservative.",
        )

    if internal_count <= 0:
        return (
            {"FULL_SNAPSHOT": 0.9, "INCREMENTAL_APPEND": 0.07, "REPLACEMENT": 0.03},
            "FULL_SNAPSHOT",
            "There are no same-day internal rows yet, so the incoming file is most likely the day snapshot.",
        )

    larger = max(internal_count, received_count)
    diff = abs(internal_count - received_count)
    diff_ratio = diff / larger if larger > 0 else 0.0

    if any(token in lowered for token in snapshot_tokens) and diff_ratio <= 0.2:
        return (
            {"FULL_SNAPSHOT": 0.86, "INCREMENTAL_APPEND": 0.1, "REPLACEMENT": 0.04},
            "FULL_SNAPSHOT",
            "Filename hints at a day snapshot and the row counts are still in the same operating range, so full snapshot remains the best fit.",
        )

    # Allow small count gaps in large files without downgrading to append.
    full_snapshot_tolerance = max(10, int(larger * 0.05))
    if diff <= full_snapshot_tolerance or diff_ratio <= 0.05:
        return (
            {"FULL_SNAPSHOT": 0.82, "INCREMENTAL_APPEND": 0.14, "REPLACEMENT": 0.04},
            "FULL_SNAPSHOT",
            "Received and internal counts are close enough that a few missing or mismatched rows still fit a full snapshot scenario.",
        )

    if any(token in lowered for token in incremental_tokens):
        return (
            {"FULL_SNAPSHOT": 0.12, "INCREMENTAL_APPEND": 0.82, "REPLACEMENT": 0.06},
            "INCREMENTAL_APPEND",
            "Filename indicates a partial batch or delta feed, so append is the most likely scope.",
        )

    if received_count < internal_count * 0.8:
        return (
            {"FULL_SNAPSHOT": 0.18, "INCREMENTAL_APPEND": 0.72, "REPLACEMENT": 0.1},
            "INCREMENTAL_APPEND",
            "The incoming file is materially smaller than the same-day internal population, which is more consistent with a partial append batch.",
        )

    return (
        {"FULL_SNAPSHOT": 0.62, "INCREMENTAL_APPEND": 0.28, "REPLACEMENT": 0.1},
        "FULL_SNAPSHOT",
        "The file does not show strong incremental or replacement signals, so the default recommendation leans toward a full-day snapshot.",
    )


def _normalize_scope_probabilities(raw: object) -> dict[str, float]:
    default = {
        "FULL_SNAPSHOT": 0.34,
        "INCREMENTAL_APPEND": 0.33,
        "REPLACEMENT": 0.33,
    }
    if not isinstance(raw, dict):
        return default

    normalized = {
        "FULL_SNAPSHOT": float(raw.get("FULL_SNAPSHOT", 0.0) or 0.0),
        "INCREMENTAL_APPEND": float(raw.get("INCREMENTAL_APPEND", 0.0) or 0.0),
        "REPLACEMENT": float(raw.get("REPLACEMENT", 0.0) or 0.0),
    }
    total = sum(max(v, 0.0) for v in normalized.values())
    if total <= 0:
        return default
    return {key: max(value, 0.0) / total for key, value in normalized.items()}


def _apply_scope_guardrails(
    *,
    ai_scope: str,
    ai_probabilities: dict[str, float],
    ai_reasoning: str,
    heuristic_scope: str,
    heuristic_probabilities: dict[str, float],
    heuristic_reasoning: str,
    internal_count: int,
    received_count: int,
    file_name: str,
) -> tuple[dict[str, float], str, str, str]:
    lowered = _normalized_filename_tokens(file_name)
    incremental_tokens = ("part", "batch", "delta", "append", "supplement", "wave")
    larger = max(internal_count, received_count, 1)
    diff = abs(internal_count - received_count)
    diff_ratio = diff / larger

    # Guardrail 1: large files with small gaps should not be forced into append.
    if ai_scope == "INCREMENTAL_APPEND" and (
        (larger >= 10_000 and diff_ratio <= 0.05)
        or (larger >= 100_000 and diff <= max(10, int(larger * 0.01)))
    ):
        return (
            heuristic_probabilities,
            heuristic_scope,
            (
                f"{ai_reasoning} Guardrail override applied: count gap is too small relative to file size "
                "to treat this as a confident append-only batch."
            ).strip(),
            "guardrail_override_small_gap",
        )

    # Guardrail 2: append should have an explicit signal when same-day counts are already close.
    if ai_scope == "INCREMENTAL_APPEND" and diff_ratio <= 0.2 and not any(
        token in lowered for token in incremental_tokens
    ):
        return (
            heuristic_probabilities,
            heuristic_scope,
            (
                f"{ai_reasoning} Guardrail override applied: append is not strongly supported by filename or volume delta."
            ).strip(),
            "guardrail_override_weak_append_signal",
        )

    return ai_probabilities, ai_scope, ai_reasoning, "llm"


def _column_index(column: object) -> int | None:
    """Convert a 1-based mapping column (number or Excel letters) to an index."""
    if isinstance(column, int):
        return column - 1 if column > 0 else None
    if not isinstance(column, str):
        return None
    value = column.strip().upper()
    if value.isdigit():
        number = int(value)
        return number - 1 if number > 0 else None
    if not value.isalpha():
        return None
    index = 0
    for character in value:
        index = index * 26 + ord(character) - ord("A") + 1
    return index - 1


def _scope_mapping_columns(
    config: object,
    structure_signature: dict | None = None,
) -> dict[str, object] | None:
    """Find the canonical fields needed to derive a reconciliation key."""
    mappings = getattr(config, "field_mappings", None) or []

    columns: dict[str, object] = {}
    for mapping in mappings:
        path = str(getattr(mapping, "path", "")).strip().lower()
        field_name = path.rsplit(".", 1)[-1]
        if field_name not in {"id", "trace", "vsptransid"}:
            continue
        column = getattr(mapping, "column", None)
        if column is not None:
            columns[field_name] = column

    if columns:
        return columns

    # Config generation is intentionally deferred for some review packets.
    # Use the source signature as a read-only fallback so scope analysis can
    # still count rows and compare an obvious transaction-id column.
    headers = (structure_signature or {}).get("headers") or []
    preferred_tokens = (
        "mstransid",
        "transactionid",
        "transid",
        "trace",
        "partnerid",
        "invoice",
        "reference",
    )
    for index, header in enumerate(headers):
        normalized = "".join(character for character in str(header).lower() if character.isalnum())
        if any(token in normalized for token in preferred_tokens):
            return {"trace": index + 1}
    return None


def _extract_scope_keys(
    rows: object,
    config: object,
    structure_signature: dict | None = None,
) -> tuple[int, set[str]]:
    """Extract unique incoming reconciliation keys without normalizing the row."""
    columns = _scope_mapping_columns(config, structure_signature)

    received_count = 0
    keys: set[str] = set()
    for row in rows:
        received_count += 1
        if columns is None:
            continue
        values: dict[str, str] = {}
        for name, column in columns.items():
            if isinstance(row, dict):
                value = row.get(column)
                if value is None and isinstance(column, int):
                    column_number = column
                    letters = ""
                    while column_number > 0:
                        column_number, remainder = divmod(column_number - 1, 26)
                        letters = chr(ord("A") + remainder) + letters
                    value = row.get(str(column)) or row.get(letters)
                if value is None and isinstance(column, str) and column.isdigit():
                    value = row.get(int(column))
            else:
                index = _column_index(column)
                value = row[index] if index is not None and index < len(row) else None
            if value is not None and str(value).strip():
                values[name] = str(value).strip()
        key = values.get("trace") or values.get("vsptransid") or values.get("id")
        if key:
            keys.add(key)
    return received_count, keys


def _apply_duplicate_overlap_guardrail(
    *,
    probabilities: dict[str, float],
    suggested_scope: str,
    reasoning: str,
    file_name: str,
    duplicate_key_count: int,
    new_key_count: int,
    incoming_key_count: int,
) -> tuple[dict[str, float], str, str, str | None]:
    """Prefer append when one file visibly combines old and new business keys."""
    if incoming_key_count <= 0 or duplicate_key_count <= 0 or new_key_count <= 0:
        return probabilities, suggested_scope, reasoning, None

    lowered = _normalized_filename_tokens(file_name)
    replacement_tokens = ("replace", "replacement", "rerun", "retry", "resend", "correct", "correction")
    duplicate_ratio = duplicate_key_count / incoming_key_count
    if duplicate_ratio < 0.5 or any(token in lowered for token in replacement_tokens):
        return probabilities, suggested_scope, reasoning, None

    return (
        {"FULL_SNAPSHOT": 0.04, "INCREMENTAL_APPEND": 0.92, "REPLACEMENT": 0.04},
        "INCREMENTAL_APPEND",
        (
            f"The incoming file overlaps {duplicate_key_count} previously ingested business keys "
            f"and adds {new_key_count} new keys ({duplicate_ratio:.0%} overlap), which is strong "
            "evidence of an incremental append batch."
        ),
        "duplicate_overlap",
    )


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


@router.get("/{packet_id}/post-approve-run/stream")
async def stream_post_approve_run(request: Request, packet_id: str):
    repo = PostApprovalRunRepository(_get_db(request))

    async def event_stream():
        last_signature: str | None = None
        while True:
            if await request.is_disconnected():
                break

            run = await repo.find_latest_by_packet_id(packet_id)
            if run is not None:
                payload = serialize_post_approval_run(run)
                signature = json.dumps(payload, sort_keys=True, default=str)
                if signature != last_signature:
                    last_signature = signature
                    yield f"event: post_approval_run\ndata: {json.dumps({'run': payload})}\n\n"
                if payload.get("status") in {"COMPLETED", "FAILED"}:
                    break
            else:
                if last_signature != "not_found":
                    last_signature = "not_found"
                    yield "event: heartbeat\ndata: {}\n\n"

            await asyncio.sleep(0.4)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
    from src.infrastructure.mapping.config_repository import MappingConfigRepository
    
    logger = logging.getLogger(__name__)
    repo = _repo(request)
    packet = await repo.find_one({"_id": packet_id})
    if packet is None:
        raise HTTPException(status_code=404, detail="Review packet not found.")
        
    db = _get_db(request)
    
    # 1. Determine date
    recon_date = getattr(packet, "reconciliation_date", None)
    if not recon_date:
        match = re.search(r'(\d{4})[-_]?(\d{2})[-_]?(\d{2})', packet.file_name)
        if match:
            try:
                recon_date = datetime.strptime(f"{match.group(1)}-{match.group(2)}-{match.group(3)}", "%Y-%m-%d")
            except ValueError:
                recon_date = datetime.now(timezone.utc)
        else:
            recon_date = datetime.now(timezone.utc)
            
    # 2. Count internal transactions
    start_of_day = datetime.combine(recon_date, datetime_time.min)
    end_of_day = datetime.combine(recon_date, datetime_time.max)
    
    from src.infrastructure.postgres.internal_transaction_repository import InternalTransactionRepository

    internal_count = await InternalTransactionRepository(
        db
    ).count_by_partner_and_date_range(
        packet.partner,
        start_of_day,
        end_of_day,
    )
    
    # 3. Count received records and collect the incoming business keys.
    received_count = 0
    incoming_keys: set[str] = set()
    source_file_path = getattr(packet, "source_file_path", None)
    if source_file_path and os.path.exists(source_file_path):
        try:
            mapping_repo = MappingConfigRepository(db)
            config = None
            if packet.draft_mapping_id:
                config = await mapping_repo.find_one({"_id": packet.draft_mapping_id})
            if config is not None:
                with create_reader(source_file_path, config) as reader:
                    received_count, incoming_keys = _extract_scope_keys(
                        reader.iter_rows(),
                        config,
                        packet.structure_signature,
                    )
            else:
                received_count = len(packet.structure_signature.get("sampleRows", [])) if packet.structure_signature else 0
        except Exception as exc:
            logger.error(f"Error counting rows in file: {exc}")
            received_count = len(packet.structure_signature.get("sampleRows", [])) if packet.structure_signature else 0
    else:
        received_count = len(packet.structure_signature.get("sampleRows", [])) if packet.structure_signature else 0

    existing_keys: set[str] = set()
    if incoming_keys:
        excluded_source_file_id = None
        try:
            if packet.source_file_id:
                excluded_source_file_id = UUID(str(packet.source_file_id))
        except (ValueError, TypeError):
            logger.warning("Ignoring invalid review packet source_file_id=%s", packet.source_file_id)
        try:
            existing_keys = await DataContainerRepository(db).find_reconciliation_keys_by_date_range(
                packet.partner,
                start_of_day,
                end_of_day,
                exclude_source_file_id=excluded_source_file_id,
            )
        except Exception as exc:
            logger.warning("Could not load existing reconciliation keys: %s", exc)

    duplicate_key_count = len(incoming_keys & existing_keys)
    new_key_count = len(incoming_keys - existing_keys)
    incoming_key_count = len(incoming_keys)
    duplicate_ratio = duplicate_key_count / incoming_key_count if incoming_key_count else 0.0

    heuristic_probabilities, heuristic_scope, heuristic_reasoning = _scope_probabilities(
        file_name=packet.file_name,
        internal_count=internal_count,
        received_count=received_count,
    )
    (
        heuristic_probabilities,
        heuristic_scope,
        heuristic_reasoning,
        overlap_resolution,
    ) = _apply_duplicate_overlap_guardrail(
        probabilities=heuristic_probabilities,
        suggested_scope=heuristic_scope,
        reasoning=heuristic_reasoning,
        file_name=packet.file_name,
        duplicate_key_count=duplicate_key_count,
        new_key_count=new_key_count,
        incoming_key_count=incoming_key_count,
    )

    analysis_config = AnalysisConfig()
    llm_provider = create_provider(analysis_config)
    system_prompt = (
        "You are an expert reconciliation analyst. "
        "Classify file scope for review workflow. "
        "You must return valid JSON only."
    )
    prompt = f"""Decide the most likely reconciliation file scope.

Valid classes:
- FULL_SNAPSHOT: the file likely represents the partner's full-day snapshot, even if a few rows are missing or mismatched.
- INCREMENTAL_APPEND: the file is likely only a partial/additive batch.
- REPLACEMENT: the file likely corrects or replaces previously seen rows.

Important guidance:
- For large files, a small row-count gap does NOT by itself disqualify FULL_SNAPSHOT.
- Example: 100000 internal rows vs 99997 partner rows can still be FULL_SNAPSHOT when the missing rows are ordinary reconciliation discrepancies.
- Do not over-weight same-day file count alone.
- Use filename hints, relative volume difference, and operational plausibility together.

Metadata:
- Partner: {packet.partner}
- File Name: {packet.file_name}
- Received Record Count: {received_count}
- Internal DB Record Count (same day): {internal_count}
- Absolute Count Gap: {abs(internal_count - received_count)}
- Relative Count Gap: {abs(internal_count - received_count) / max(internal_count, received_count, 1):.6f}
- Incoming Unique Business Key Count: {incoming_key_count}
- Keys Already Present In DB: {duplicate_key_count}
- New Business Keys: {new_key_count}
- Incoming Key Overlap Ratio: {duplicate_ratio:.6f}
- Heuristic Baseline Suggestion: {heuristic_scope}
- Heuristic Baseline Reasoning: {heuristic_reasoning}

Return JSON:
{{
  "probabilities": {{
    "FULL_SNAPSHOT": 0.0,
    "INCREMENTAL_APPEND": 0.0,
    "REPLACEMENT": 0.0
  }},
  "suggested_scope": "FULL_SNAPSHOT",
  "reasoning": "short explanation"
}}
"""

    resolution = "rule_based_duplicate_overlap" if overlap_resolution else "rule_based"
    probabilities = heuristic_probabilities
    suggested_scope = heuristic_scope
    reasoning = heuristic_reasoning
    try:
        response_text = await asyncio.wait_for(
            llm_provider.generate(prompt=prompt, system_prompt=system_prompt),
            timeout=min(float(analysis_config.timeout), _SCOPE_LLM_TIMEOUT_SECONDS),
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Scope classification LLM timed out; returning heuristic result"
        )
        response_text = None
        resolution = "rule_based_timeout"
    if response_text:
        try:
            clean_text = response_text.strip()
            if clean_text.startswith("```"):
                parts = clean_text.split("```")
                if len(parts) >= 3:
                    clean_text = parts[1]
                    if clean_text.startswith("json"):
                        clean_text = clean_text[4:]
            clean_text = clean_text.strip()
            parsed = json.loads(clean_text)
            ai_probabilities = _normalize_scope_probabilities(parsed.get("probabilities"))
            ai_scope = str(parsed.get("suggested_scope") or heuristic_scope).strip().upper()
            if ai_scope not in {"FULL_SNAPSHOT", "INCREMENTAL_APPEND", "REPLACEMENT"}:
                ai_scope = heuristic_scope
            ai_reasoning = str(parsed.get("reasoning") or heuristic_reasoning).strip()
            probabilities, suggested_scope, reasoning, resolution = _apply_scope_guardrails(
                ai_scope=ai_scope,
                ai_probabilities=ai_probabilities,
                ai_reasoning=ai_reasoning,
                heuristic_scope=heuristic_scope,
                heuristic_probabilities=heuristic_probabilities,
                heuristic_reasoning=heuristic_reasoning,
                internal_count=internal_count,
                received_count=received_count,
                file_name=packet.file_name,
            )
            (
                probabilities,
                suggested_scope,
                reasoning,
                overlap_resolution,
            ) = _apply_duplicate_overlap_guardrail(
                probabilities=probabilities,
                suggested_scope=suggested_scope,
                reasoning=reasoning,
                file_name=packet.file_name,
                duplicate_key_count=duplicate_key_count,
                new_key_count=new_key_count,
                incoming_key_count=incoming_key_count,
            )
            if overlap_resolution:
                resolution = "guardrail_override_duplicate_overlap"
        except Exception as exc:
            logger.warning(f"Scope classification JSON parse failed: {exc}")
        
    return {
        "ok": True,
        "internalDbRecordCount": internal_count,
        "receivedRecordCount": received_count,
        "probabilities": probabilities,
        "suggestedScope": suggested_scope,
        "reasoning": reasoning,
        "resolution": resolution,
        "scopeEvidence": {
            "incomingUniqueBusinessKeyCount": incoming_key_count,
            "duplicateBusinessKeyCount": duplicate_key_count,
            "newBusinessKeyCount": new_key_count,
            "duplicateRatio": duplicate_ratio,
            "available": bool(incoming_keys),
        },
        "heuristicBaseline": {
            "suggestedScope": heuristic_scope,
            "probabilities": heuristic_probabilities,
            "reasoning": heuristic_reasoning,
        },
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
