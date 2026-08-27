"""Bounded quarantine query and operator-action endpoints."""

from collections.abc import Mapping
from datetime import datetime
import inspect
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from src.api.actor import require_actor
from src.api.dependencies import get_request_db as _get_db
from src.application.ingestion.quarantine_reprocessing import (
    QuarantineReprocessMode,
    QuarantineReprocessRequest,
)
from src.application.ingestion.quarantine_service import (
    QuarantineResolutionResult,
    QuarantineResolutionService,
)
from src.application.ingestion.source_unit_resume import resume_quarantined_source_unit
from src.domain.ingestion.quarantine import (
    IngestionQuarantineRecord,
    QuarantinePhase,
    QuarantinePriority,
    QuarantineQuery,
    QuarantineStatus,
    sanitize_raw_row,
)
from src.infrastructure.ingestion.composition import build_quarantine_resolution_service
from src.infrastructure.ingestion.quarantine_repository import IngestionQuarantineRepository


router = APIRouter(prefix="/api/v1/quarantine")


class QuarantineClaimPayload(BaseModel):
    """Input for an explicit ownership claim."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    operator_id: str | None = Field(default=None, alias="operatorId", max_length=128)
    action_id: str = Field(alias="actionId", min_length=1, max_length=128)
    expected_status: QuarantineStatus = Field(alias="expectedStatus")


class QuarantineReprocessPayload(BaseModel):
    """Input for source replay or corrected-row reprocessing."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    operator_id: str | None = Field(default=None, alias="operatorId", max_length=128)
    action_id: str = Field(alias="actionId", min_length=1, max_length=128)
    expected_status: QuarantineStatus = Field(alias="expectedStatus")
    mode: QuarantineReprocessMode = QuarantineReprocessMode.REPLAY_SOURCE_ROW
    corrected_row: Any | None = Field(default=None, alias="correctedRow")
    mapping_version: str | None = Field(default=None, alias="mappingVersion")
    reason: str | None = Field(default=None, max_length=500)


class QuarantineAcceptExistingPayload(BaseModel):
    """Input for accepting an unchanged existing transaction."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    operator_id: str | None = Field(default=None, alias="operatorId", max_length=128)
    action_id: str = Field(alias="actionId", min_length=1, max_length=128)
    expected_status: QuarantineStatus = Field(alias="expectedStatus")
    expected_existing_fingerprint: str | None = Field(
        default=None,
        alias="expectedExistingFingerprint",
        min_length=1,
    )
    reason: str | None = Field(default=None, max_length=500)


class QuarantineRejectPayload(BaseModel):
    """Input for an explicit terminal rejection."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    operator_id: str | None = Field(default=None, alias="operatorId", max_length=128)
    action_id: str = Field(alias="actionId", min_length=1, max_length=128)
    expected_status: QuarantineStatus = Field(alias="expectedStatus")
    reason: str = Field(min_length=1, max_length=500)


class QuarantineEscalatePayload(BaseModel):
    """Input for a status-preserving escalation."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    operator_id: str | None = Field(default=None, alias="operatorId", max_length=128)
    action_id: str = Field(alias="actionId", min_length=1, max_length=128)
    expected_status: QuarantineStatus = Field(alias="expectedStatus")
    reason: str = Field(min_length=1, max_length=500)


class QuarantineSourceUnitResumePayload(BaseModel):
    """Input for resuming a held source unit after quarantine review."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    operator_id: str | None = Field(default=None, alias="operatorId")
    reason: str = Field(min_length=1)


_SENSITIVE_METADATA_KEYS = (
    "raw",
    "fingerprint",
    "password",
    "secret",
    "token",
    "credential",
    "authorization",
    "exception",
    "trace",
    "stack",
)


def _bounded_value(
    value: Any,
    *,
    depth: int = 0,
    drop_sensitive: bool = False,
) -> Any:
    if depth > 2:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        bounded: dict[str, Any] = {}
        for key, item in list(value.items())[:30]:
            key_text = str(key)
            normalized = "".join(character for character in key_text.lower() if character.isalnum())
            if drop_sensitive and any(token in normalized for token in _SENSITIVE_METADATA_KEYS):
                continue
            if drop_sensitive and (
                normalized == "error"
                or normalized.startswith("error") and normalized != "errorcode"
            ):
                continue
            bounded[key_text] = _bounded_value(
                item,
                depth=depth + 1,
                drop_sensitive=drop_sensitive,
            )
        return bounded
    if isinstance(value, (list, tuple)):
        return [
            _bounded_value(item, depth=depth + 1, drop_sensitive=drop_sensitive)
            for item in list(value)[:50]
        ]
    if isinstance(value, str) and len(value) > 512:
        return f"{value[:509]}..."
    if hasattr(value, "isoformat") and not isinstance(value, (str, bytes)):
        return value.isoformat()
    return str(value) if hasattr(value, "hex") else value


def _error_code(error: Any) -> str | None:
    if not isinstance(error, Mapping):
        return None
    value = error.get("errorCode") or error.get("error_code") or error.get("code")
    return str(value) if value else None


def _bounded_history(record: IngestionQuarantineRecord) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for event in record.resolution_history[:50]:
        payload = event.model_dump(mode="json", by_alias=True)
        payload["metadata"] = _bounded_value(
            payload.get("metadata") or {}, drop_sensitive=True
        )
        history.append(payload)
    return history


def _bounded_record(
    record: IngestionQuarantineRecord,
    *,
    include_evidence: bool = False,
) -> dict[str, Any]:
    payload = record.model_dump(mode="json", by_alias=True)
    result: dict[str, Any] = {
        "_id": str(record.id),
        "sourceFileId": payload["sourceFileId"],
        "sourceUnitKey": payload.get("sourceUnitKey"),
        "partner": payload["partner"],
        "reconciliationDate": payload["reconciliationDate"],
        "rowNumber": payload.get("rowNumber"),
        "phase": payload["phase"],
        "severity": payload["severity"],
        "configVersion": payload.get("configVersion"),
        "status": payload["status"],
        "attemptCount": payload["attemptCount"],
        "claimedBy": payload.get("claimedBy"),
        "claimedAt": payload.get("claimedAt"),
        "claimExpiresAt": payload.get("claimExpiresAt"),
        "priority": payload.get("priority"),
        "reviewDueAt": payload.get("reviewDueAt"),
        "escalationLevel": payload.get("escalationLevel", 0),
        "escalatedAt": payload.get("escalatedAt"),
        "escalatedBy": payload.get("escalatedBy"),
        "lastActionId": payload.get("lastActionId"),
        "errorCodes": [code for code in (_error_code(error) for error in record.errors) if code],
        "resolutionMetadata": _bounded_value(
            payload.get("resolutionMetadata") or {}, drop_sensitive=True
        ),
        "createdAt": payload["createdAt"],
        "updatedAt": payload["updatedAt"],
        "retentionUntil": payload.get("retentionUntil"),
    }
    if include_evidence:
        result["rawRow"] = _bounded_value(sanitize_raw_row(record.raw_row))
        result["errors"] = [
            _bounded_value(
                {key: value for key, value in error.items() if key != "rawRow"},
                drop_sensitive=True,
            )
            for error in record.errors[:20]
        ]
        result["resolutionHistory"] = _bounded_history(record)
    return result


def _result_payload(result: QuarantineResolutionResult) -> dict[str, Any]:
    error_codes = [
        code
        for code in (_error_code(error) for error in result.errors[:20])
        if code
    ]
    if not result.success and result.outcome not in error_codes:
        error_codes.insert(0, result.outcome)
    return {
        "recordId": result.record_id,
        "actionId": result.action_id,
        "outcome": result.outcome,
        "previousStatus": (
            result.previous_status.value if result.previous_status is not None else None
        ),
        "status": result.status.value if result.status is not None else None,
        "attemptCount": result.attempt_count,
        "claimedBy": result.claimed_by,
        "priority": result.priority.value if result.priority is not None else None,
        "reviewDueAt": (
            result.review_due_at.isoformat() if result.review_due_at is not None else None
        ),
        "escalationLevel": result.escalation_level,
        "sourceEvidenceAvailable": result.source_evidence_available,
        "qualityCounters": dict(result.quality_counters),
        "errorCodes": error_codes,
    }


def _raise_operation_error(result: QuarantineResolutionResult) -> None:
    if result.success:
        return
    if result.outcome in {
        "CLAIM_NOT_ACQUIRED",
        "STALE_STATUS",
        "WRONG_OWNER",
        "RESOLUTION_CONFLICT",
        "FINGERPRINT_MISMATCH",
        "ACTION_ID_REUSE_CONFLICT",
        "ESCALATION_CONFLICT",
    }:
        raise HTTPException(status_code=409, detail=_result_payload(result))
    if result.outcome in {
        "REASON_REQUIRED",
        "INPUT_UNAVAILABLE",
        "CORRECTED_ROW_REQUIRED",
        "SOURCE_EVIDENCE_UNAVAILABLE",
        "VALIDATION_FAILED",
        "FINGERPRINT_UNAVAILABLE",
    }:
        raise HTTPException(status_code=422, detail=_result_payload(result))
    if result.outcome == "RECORD_NOT_FOUND":
        raise HTTPException(status_code=404, detail=_result_payload(result))
    if result.outcome == "RETRYABLE_FAILURE":
        raise HTTPException(status_code=503, detail=_result_payload(result))
    raise HTTPException(status_code=422, detail=_result_payload(result))


def _resolution_service(request: Request) -> QuarantineResolutionService:
    return build_quarantine_resolution_service(_get_db(request))


@router.get("")
async def list_quarantine(
    request: Request,
    partner: str | None = Query(default=None),
    status: QuarantineStatus | None = Query(default=None),
    phase: QuarantinePhase | None = Query(default=None),
    error_code: str | None = Query(default=None, alias="errorCode"),
    source_file_id: str | None = Query(default=None, alias="sourceFileId"),
    source_unit_key: str | None = Query(default=None, alias="sourceUnitKey"),
    claimed_by: str | None = Query(default=None, alias="claimedBy"),
    priority: QuarantinePriority | None = Query(default=None),
    overdue: bool | None = Query(default=None),
    from_date: datetime | None = Query(default=None, alias="fromDate"),
    to_date: datetime | None = Query(default=None, alias="toDate"),
    limit: int = Query(default=100, ge=1, le=200),
    cursor: str | None = Query(default=None),
):
    repository = IngestionQuarantineRepository(_get_db(request))
    partner_value = partner if isinstance(partner, str) else None
    status_value = status if isinstance(status, QuarantineStatus) else None
    phase_value = phase if isinstance(phase, QuarantinePhase) else None
    error_code_value = error_code if isinstance(error_code, str) else None
    source_file_id_value = source_file_id if isinstance(source_file_id, str) else None
    source_unit_key_value = source_unit_key if isinstance(source_unit_key, str) else None
    claimed_by_value = claimed_by if isinstance(claimed_by, str) else None
    priority_value = priority if isinstance(priority, QuarantinePriority) else None
    overdue_value = overdue if isinstance(overdue, bool) else None
    from_date_value = from_date if isinstance(from_date, datetime) else None
    to_date_value = to_date if isinstance(to_date, datetime) else None
    limit_value = limit if isinstance(limit, int) else 100
    cursor_value = cursor if isinstance(cursor, str) else None
    query = QuarantineQuery(
        partner=partner_value,
        status=status_value,
        phase=phase_value,
        errorCode=error_code_value,
        sourceFileId=source_file_id_value,
        sourceUnitKey=source_unit_key_value,
        claimedBy=claimed_by_value,
        priority=priority_value,
        overdue=overdue_value,
        fromDate=from_date_value,
        toDate=to_date_value,
        limit=limit_value,
        cursor=cursor_value,
    )
    records, next_cursor = await repository.find_many(query)
    summary_call = getattr(repository, "summarize", None)
    summary: dict[str, int] | None = None
    if callable(summary_call):
        summary_value = summary_call(
            query.model_copy(update={"limit": 200, "cursor": None})
        )
        if inspect.isawaitable(summary_value):
            summary_value = await summary_value
        if isinstance(summary_value, Mapping):
            summary = {
                key: int(summary_value.get(key, 0) or 0)
                for key in (
                    "pending",
                    "reprocessing",
                    "resolved",
                    "rejected",
                    "overdue",
                    "highPriority",
                )
            }
    if summary is None:
        now = datetime.now().astimezone()
        summary = {
            "pending": sum(record.status is QuarantineStatus.PENDING for record in records),
            "reprocessing": sum(
                record.status is QuarantineStatus.REPROCESSING for record in records
            ),
            "resolved": sum(record.status is QuarantineStatus.RESOLVED for record in records),
            "rejected": sum(record.status is QuarantineStatus.REJECTED for record in records),
            "overdue": sum(
                record.status in {
                    QuarantineStatus.PENDING,
                    QuarantineStatus.REPROCESSING,
                }
                and record.review_due_at is not None
                and record.review_due_at <= now
                for record in records
            ),
            "highPriority": sum(
                record.priority is QuarantinePriority.HIGH for record in records
            ),
        }
    return {
        "items": [_bounded_record(record) for record in records],
        "nextCursor": next_cursor,
        "limit": limit_value,
        "summary": summary,
    }


@router.get("/{record_id}")
async def get_quarantine_record(request: Request, record_id: str):
    record = await IngestionQuarantineRepository(_get_db(request)).find_by_id(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Quarantine record not found.")
    return _bounded_record(record, include_evidence=True)


@router.post("/{record_id}/claim")
async def claim_quarantine_record(
    request: Request,
    record_id: str,
    payload: QuarantineClaimPayload,
):
    actor = require_actor(request, payload_actor=payload.operator_id, payload_field_name="operatorId")
    result = await _resolution_service(request).claim(
        record_id,
        actor,
        payload.action_id,
        payload.expected_status,
    )
    _raise_operation_error(result)
    return _result_payload(result)


@router.post("/{record_id}/reprocess")
async def reprocess_quarantine_record(
    request: Request,
    record_id: str,
    payload: QuarantineReprocessPayload,
):
    actor = require_actor(request, payload_actor=payload.operator_id, payload_field_name="operatorId")
    command = QuarantineReprocessRequest(
        recordId=record_id,
        operatorId=actor,
        actionId=payload.action_id,
        expectedStatus=payload.expected_status,
        mode=payload.mode,
        correctedRow=payload.corrected_row,
        mappingVersion=payload.mapping_version,
        reason=payload.reason,
    )
    result = await _resolution_service(request).resolve_claimed(command)
    _raise_operation_error(result)
    return _result_payload(result)


@router.post("/{record_id}/accept-existing")
async def accept_existing_quarantine_record(
    request: Request,
    record_id: str,
    payload: QuarantineAcceptExistingPayload,
):
    actor = require_actor(request, payload_actor=payload.operator_id, payload_field_name="operatorId")
    command = QuarantineReprocessRequest(
        recordId=record_id,
        operatorId=actor,
        actionId=payload.action_id,
        expectedStatus=payload.expected_status,
        mode=QuarantineReprocessMode.ACCEPT_EXISTING,
        expectedExistingFingerprint=payload.expected_existing_fingerprint,
        reason=payload.reason,
    )
    result = await _resolution_service(request).resolve_claimed(command)
    _raise_operation_error(result)
    return _result_payload(result)


@router.post("/{record_id}/reject")
async def reject_quarantine_record(
    request: Request,
    record_id: str,
    payload: QuarantineRejectPayload,
):
    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A non-empty rejection reason is required.")
    actor = require_actor(request, payload_actor=payload.operator_id, payload_field_name="operatorId")
    command = QuarantineReprocessRequest(
        recordId=record_id,
        operatorId=actor,
        actionId=payload.action_id,
        expectedStatus=payload.expected_status,
        mode=QuarantineReprocessMode.REJECT,
        reason=reason,
    )
    result = await _resolution_service(request).resolve_claimed(command)
    _raise_operation_error(result)
    return _result_payload(result)


@router.post("/{record_id}/escalate")
async def escalate_quarantine_record(
    request: Request,
    record_id: str,
    payload: QuarantineEscalatePayload,
):
    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A non-empty escalation reason is required.")
    actor = require_actor(request, payload_actor=payload.operator_id, payload_field_name="operatorId")
    result = await _resolution_service(request).escalate(
        record_id,
        actor,
        payload.action_id,
        payload.expected_status,
        reason,
    )
    _raise_operation_error(result)
    return _result_payload(result)


@router.post("/source-units/{source_unit_key}/resume")
async def resume_quarantine_source_unit(
    request: Request,
    source_unit_key: str,
    payload: QuarantineSourceUnitResumePayload,
):
    actor = require_actor(request, payload_actor=payload.operator_id, payload_field_name="operatorId")
    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A non-empty resume reason is required.")
    try:
        return await resume_quarantined_source_unit(
            _get_db(request),
            source_unit_key,
            operator_id=actor,
            reason=reason,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


__all__ = [
    "QuarantineAcceptExistingPayload",
    "QuarantineClaimPayload",
    "QuarantineEscalatePayload",
    "QuarantineRejectPayload",
    "QuarantineReprocessPayload",
    "get_quarantine_record",
    "claim_quarantine_record",
    "escalate_quarantine_record",
    "list_quarantine",
    "reprocess_quarantine_record",
    "accept_existing_quarantine_record",
    "reject_quarantine_record",
    "QuarantineSourceUnitResumePayload",
    "resume_quarantine_source_unit",
    "router",
]
