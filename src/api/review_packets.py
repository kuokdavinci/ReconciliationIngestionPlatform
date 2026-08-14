"""Approval desk review packet endpoints."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api.actor import require_actor
from src.api.background_tasks import track_background_task
from src.config.ai_generator import generate_config_from_samples
from src.domain.mapping.models import MappingConfig
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
from src.application.review.actions import (
    approve_packet_mapping_and_reprocess,
    reprocess_packet_with_current_mapping,
    mark_packet,
    update_packet_scope,
)
from src.application.review.reprocessing import serialize_post_approval_run
from src.infrastructure.mapping.composition import build_config_loader
from src.application.review.ai_mapping_context import resolve_ai_generation_context
from src.application.review.runtime_validation import (
    derive_validation_state,
    run_runtime_validation,
)
from src.application.review.raw_stream import read_review_stream_page
from src.application.review.mapping_workflow import ReviewMappingWorkflow
from src.application.review.scope_classification import (
    ScopeClassificationCommand,
    ScopeClassificationService,
)
from src.application.review.errors import (
    ReviewConflictError,
    ReviewError,
    ReviewNotFoundError,
    ReviewUnavailableError,
    ReviewValidationError,
)
from src.config.signature import structure_signatures_equivalent


router = APIRouter(prefix="/api/v1/review-packets")
_SCOPE_LLM_TIMEOUT_SECONDS = 8.0
_REVIEW_ERROR_STATUS: dict[type[ReviewError], int] = {
    ReviewNotFoundError: 404,
    ReviewConflictError: 409,
    ReviewValidationError: 400,
    ReviewUnavailableError: 503,
}


def _review_error_status(error: ReviewError) -> int:
    for error_type, status_code in _REVIEW_ERROR_STATUS.items():
        if isinstance(error, error_type):
            return status_code
    return 400


async def _run_review_operation(awaitable):
    try:
        return await awaitable
    except ReviewError as exc:
        raise HTTPException(status_code=_review_error_status(exc), detail=str(exc)) from exc


def _scope_probabilities(
    *,
    internal_count: int,
    received_count: int,
) -> tuple[dict[str, float], str, str]:
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

    # Counts alone are only a fallback. Key evidence below has precedence.
    full_snapshot_tolerance = max(10, int(larger * 0.05))
    if diff <= full_snapshot_tolerance or diff_ratio <= 0.05:
        return (
            {"FULL_SNAPSHOT": 0.82, "INCREMENTAL_APPEND": 0.14, "REPLACEMENT": 0.04},
            "FULL_SNAPSHOT",
            "Received and internal counts are close enough that a few missing or mismatched rows still fit a full snapshot scenario.",
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
) -> tuple[dict[str, float], str, str, str]:
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


def _apply_source_reference_strategy(
    mappings: list[dict],
    *,
    headers: list[str],
    source_file_name: str | None,
) -> list[dict]:
    """Use object field names when samples originate from a JSON-like source.

    AI generation is column-oriented because it must also support tabular
    files. JSON readers yield dictionaries, though, so their canonical mapping
    must point to the discovered key rather than a numeric column position.
    The decision is based on the source representation, not on a partner.
    """
    suffix = Path(source_file_name or "").suffix.lower()
    if suffix not in {".json", ".jsonl", ".ndjson"}:
        return [dict(mapping) for mapping in mappings]

    normalized: list[dict] = []
    for mapping in mappings:
        item = dict(mapping)
        index = _column_index(item.get("column"))
        if index is not None and index < len(headers):
            source_field = str(headers[index]).strip()
            if source_field:
                item.pop("column", None)
                item["sourceField"] = source_field
        normalized.append(item)
    return normalized


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


async def _raw_stage_record_count(db, packet: ReviewPacket) -> int | None:
    """Count all records retained for a paginated API review packet.

    ``sourceFilePath`` points to one materialized page, not to the complete
    API stream. ``itemCount`` is persisted per raw page and is therefore the
    correct bounded metadata source for the total received count.
    """

    if not packet.raw_stage_key:
        return None
    try:
        cursor = db["raw_ingestion_page"].find(
            {
                "partner": packet.partner,
                "stageKey": packet.raw_stage_key,
                "status": {"$in": ["STAGED", "CONSUMED"]},
            },
            projection={"itemCount": 1},
        )
        documents = await cursor.to_list(length=None)
    except Exception:
        return None
    if not documents:
        return None
    return sum(
        int(document.get("itemCount") or 0)
        for document in documents
        if isinstance(document, dict)
    )


def _get_db(request: Request):
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available.")
    return db


def _repo(request: Request) -> ReviewPacketRepository:
    return ReviewPacketRepository(_get_db(request))


def _config_loader(request: Request):
    return build_config_loader(_get_db(request))


def _review_mapping_workflow(request: Request) -> ReviewMappingWorkflow:
    return ReviewMappingWorkflow(
        db=_get_db(request),
        packet_repo=_repo(request),
        mapping_repo=MappingConfigRepository(_get_db(request)),
        context_resolver=resolve_ai_generation_context,
        config_generator=generate_config_from_samples,
        approve_activate_action=approve_packet_mapping_and_reprocess,
        approve_keep_current_action=reprocess_packet_with_current_mapping,
        mark_packet=mark_packet,
        update_packet_scope=update_packet_scope,
        schedule_background=lambda awaitable: _schedule_background(request, awaitable),
        workflow_gateway=getattr(request.app.state, "workflow_gateway", None),
        packet_serializer=_serialize,
        next_version=lambda partner: _next_pending_version(request, partner),
    )


def _scope_classification_service(request: Request) -> ScopeClassificationService:
    from src.analysis import config as analysis_config_module
    from src.analysis import provider as provider_module

    async def existing_keys(packet, start_of_day, end_of_day, incoming_keys):
        if not incoming_keys:
            return set()
        return await DataContainerRepository(_get_db(request)).find_reconciliation_keys_by_date_range(
            packet.partner,
            start_of_day,
            end_of_day,
            exclude_source_file_id=None,
        )

    return ScopeClassificationService(
        db=_get_db(request),
        packet_repo=_repo(request),
        llm_provider_factory=provider_module.create_provider,
        analysis_config=analysis_config_module.AnalysisConfig(),
        existing_keys_loader=existing_keys,
    )


async def _run_mapping_review_operation(awaitable):
    try:
        return await awaitable
    except ReviewError as exc:
        raise HTTPException(status_code=_review_error_status(exc), detail=str(exc)) from exc


def _schedule_background(request: Request, awaitable) -> None:
    task = asyncio.create_task(awaitable)
    track_background_task(request.app, task)


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
    requested_status = status.upper() if isinstance(status, str) and status else None
    if partner:
        query["partner"] = partner
    packets = await _repo(request).find_many(query)
    packets.sort(key=lambda item: item.created_at, reverse=True)
    approved_shapes: dict[tuple[str, str, str], list[dict]] = {}
    for packet in packets:
        if packet.status != ReviewPacketStatus.APPROVED:
            continue
        key = (packet.partner, packet.source_type.value, packet.file_type_detected)
        approved_shapes.setdefault(key, []).append(packet.structure_signature or {})

    seen_pending_scheduler_keys: set[tuple[str, str, str]] = set()
    visible_packets = []
    for packet in packets:
        packet_key = (packet.partner, packet.source_type.value, packet.file_type_detected)
        if (
            packet.status == ReviewPacketStatus.PENDING
            and packet.source_type == ReviewPacketSourceType.SCHEDULER_JOB
            and any(
                structure_signatures_equivalent(packet.structure_signature, approved_shape)
                for approved_shape in approved_shapes.get(packet_key, [])
            )
        ):
            # A backfill approval covers the same structure for the full
            # parent run. Keep the duplicate document for audit, but do not
            # surface it as a second actionable review packet.
            continue
        if (
            packet.source_type == ReviewPacketSourceType.SCHEDULER_JOB
            and packet.status == ReviewPacketStatus.PENDING
        ):
            if packet_key in seen_pending_scheduler_keys:
                continue
            seen_pending_scheduler_keys.add(packet_key)
        visible_packets.append(packet)
    if requested_status:
        visible_packets = [
            packet
            for packet in visible_packets
            if packet.status.value == requested_status
        ]
    return {"packets": [_serialize(packet) for packet in visible_packets]}


@router.get("/{packet_id}")
async def get_review_packet(request: Request, packet_id: str):
    packet = await _repo(request).find_one({"_id": packet_id})
    if packet is None:
        raise HTTPException(status_code=404, detail="Review packet not found.")
    return {"packet": _serialize(packet)}


@router.get("/{packet_id}/raw-records")
async def get_review_packet_raw_records(
    request: Request,
    packet_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Read complete raw records for the packet's staged stream."""

    packet = await _repo(request).find_one({"_id": packet_id})
    if packet is None:
        raise HTTPException(status_code=404, detail="Review packet not found.")
    if not packet.raw_stage_key and not packet.source_file_path:
        raise HTTPException(
            status_code=409,
            detail="Review packet has neither rawStageKey nor sourceFilePath evidence.",
        )
    try:
        return await read_review_stream_page(
            db=_get_db(request),
            packet=packet,
            offset=offset,
            limit=limit,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=410,
            detail=f"Review packet source evidence is no longer available: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
    return await _run_mapping_review_operation(
        _review_mapping_workflow(request).generate(packet_id, force=force)
    )

@router.post("/{packet_id}/save-draft-mapping")
async def save_draft_mapping_for_packet(
    request: Request,
    packet_id: str,
    payload: SaveDraftMappingPayload,
):
    return await _run_mapping_review_operation(
        _review_mapping_workflow(request).save(
            packet_id,
            field_mappings=payload.field_mappings,
            sheet_name=payload.sheet_name,
            start_row=payload.start_row,
        )
    )

async def approve_activate_packet_action(
    request: Request,
    packet_id: str,
    payload: ReviewDecisionPayload,
):
    payload.reviewed_by = require_actor(request, payload_actor=payload.reviewed_by)
    return await _run_mapping_review_operation(
        _review_mapping_workflow(request).approve_activate(
            packet_id,
            actor=payload.reviewed_by,
            scope_type=payload.scope_type,
        )
    )

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
    return await _run_mapping_review_operation(
        _review_mapping_workflow(request).approve_keep_current(
            packet_id,
            actor=payload.reviewed_by,
            scope_type=payload.scope_type,
        )
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
    return await _run_mapping_review_operation(
        _review_mapping_workflow(request).reject(packet_id, actor=payload.reviewed_by)
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
    try:
        return await _scope_classification_service(request).classify(
            ScopeClassificationCommand(packet_id=packet_id, force=force)
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

class ScopeUpdatePayload(BaseModel):
    scope_type: str = Field(alias="scopeType")


@router.post("/{packet_id}/scope")
async def update_packet_scope_endpoint(request: Request, packet_id: str, payload: ScopeUpdatePayload):
    repo = _repo(request)
    packet = await repo.find_one({"_id": packet_id})
    if packet is None:
        raise HTTPException(status_code=404, detail="Review packet not found.")
        
    await _run_review_operation(
        update_packet_scope(_get_db(request), packet_id, packet, payload.scope_type)
    )
    return {"ok": True, "scopeType": payload.scope_type}
