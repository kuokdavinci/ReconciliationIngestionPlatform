"""Bounded quarantine query and operator-action endpoints."""

from collections.abc import Mapping
from datetime import datetime
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
    QuarantineQuery,
    QuarantineStatus,
    sanitize_raw_row,
)
from src.infrastructure.ingestion.composition import build_quarantine_resolution_service
from src.infrastructure.ingestion.quarantine_repository import IngestionQuarantineRepository


router = APIRouter(prefix="/api/v1/quarantine")


class QuarantineReprocessPayload(BaseModel):
    """Input for source replay or corrected-row reprocessing."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    operator_id: str | None = Field(default=None, alias="operatorId")
    mode: QuarantineReprocessMode = QuarantineReprocessMode.REPLAY_SOURCE_ROW
    corrected_row: Any | None = Field(default=None, alias="correctedRow")
    mapping_version: str | None = Field(default=None, alias="mappingVersion")
    reason: str | None = None


class QuarantineAcceptExistingPayload(BaseModel):
    """Input for accepting an unchanged existing transaction."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    operator_id: str | None = Field(default=None, alias="operatorId")
    expected_existing_fingerprint: str = Field(
        alias="expectedExistingFingerprint",
        min_length=1,
    )
    reason: str | None = None


class QuarantineRejectPayload(BaseModel):
    """Input for an explicit terminal rejection."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    operator_id: str | None = Field(default=None, alias="operatorId")
    reason: str = Field(min_length=1)


class QuarantineSourceUnitResumePayload(BaseModel):
    """Input for resuming a held source unit after quarantine review."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    operator_id: str | None = Field(default=None, alias="operatorId")
    reason: str = Field(min_length=1)


def _bounded_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 2:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        return {
            str(key): _bounded_value(item, depth=depth + 1)
            for key, item in list(value.items())[:30]
        }
    if isinstance(value, (list, tuple)):
        return [_bounded_value(item, depth=depth + 1) for item in list(value)[:50]]
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
        payload["metadata"] = _bounded_value(payload.get("metadata") or {})
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
        "incomingFingerprint": payload.get("incomingFingerprint"),
        "existingFingerprint": payload.get("existingFingerprint"),
        "errorCodes": [code for code in (_error_code(error) for error in record.errors) if code],
        "lastAttemptError": payload.get("lastAttemptError"),
        "resolutionMetadata": _bounded_value(payload.get("resolutionMetadata") or {}),
        "createdAt": payload["createdAt"],
        "updatedAt": payload["updatedAt"],
        "retentionUntil": payload.get("retentionUntil"),
    }
    if include_evidence:
        result["rawRow"] = _bounded_value(sanitize_raw_row(record.raw_row))
        result["errors"] = [
            _bounded_value({key: value for key, value in error.items() if key != "rawRow"})
            for error in record.errors[:20]
        ]
        result["resolutionHistory"] = _bounded_history(record)
    return result


def _result_payload(result: QuarantineResolutionResult) -> dict[str, Any]:
    return {
        "recordId": result.record_id,
        "success": result.success,
        "status": result.status.value if result.status is not None else None,
        "outcome": result.outcome,
        "action": result.action.value,
        "reason": result.reason,
        "errors": result.errors[:20],
        "qualityCounters": dict(result.quality_counters),
        "failureClassification": result.failure_classification,
    }


def _raise_operation_error(result: QuarantineResolutionResult) -> None:
    if result.success:
        return
    if result.outcome in {
        "CLAIM_NOT_ACQUIRED",
        "RESOLUTION_CONFLICT",
        "FINGERPRINT_MISMATCH",
    }:
        raise HTTPException(status_code=409, detail=_result_payload(result))
    if result.outcome in {
        "REASON_REQUIRED",
        "INPUT_UNAVAILABLE",
        "VALIDATION_FAILED",
        "FINGERPRINT_UNAVAILABLE",
    }:
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
    from_date: datetime | None = Query(default=None, alias="fromDate"),
    to_date: datetime | None = Query(default=None, alias="toDate"),
    limit: int = Query(default=100, ge=1, le=200),
    cursor: str | None = Query(default=None),
):
    repository = IngestionQuarantineRepository(_get_db(request))
    from_date_value = from_date if isinstance(from_date, datetime) else None
    to_date_value = to_date if isinstance(to_date, datetime) else None
    records, next_cursor = await repository.find_many(
        QuarantineQuery(
            partner=partner,
            status=status,
            phase=phase,
            errorCode=error_code,
            sourceFileId=source_file_id,
            sourceUnitKey=source_unit_key,
            fromDate=from_date_value,
            toDate=to_date_value,
            limit=limit,
            cursor=cursor,
        )
    )
    return {
        "items": [_bounded_record(record) for record in records],
        "nextCursor": next_cursor,
        "limit": limit,
    }


@router.get("/{record_id}")
async def get_quarantine_record(request: Request, record_id: str):
    record = await IngestionQuarantineRepository(_get_db(request)).find_by_id(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Quarantine record not found.")
    return _bounded_record(record, include_evidence=True)


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
        mode=payload.mode,
        correctedRow=payload.corrected_row,
        mappingVersion=payload.mapping_version,
        reason=payload.reason,
    )
    result = await _resolution_service(request).resolve(command)
    _raise_operation_error(result)
    return _result_payload(result)


@router.post("/{record_id}/accept-existing")
async def accept_existing_quarantine_record(
    request: Request,
    record_id: str,
    payload: QuarantineAcceptExistingPayload,
):
    actor = require_actor(request, payload_actor=payload.operator_id, payload_field_name="operatorId")
    repository = IngestionQuarantineRepository(_get_db(request))
    record = await repository.find_by_id(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Quarantine record not found.")
    if payload.expected_existing_fingerprint != record.existing_fingerprint:
        raise HTTPException(status_code=409, detail="Existing fingerprint does not match quarantine evidence.")
    command = QuarantineReprocessRequest(
        recordId=record_id,
        operatorId=actor,
        mode=QuarantineReprocessMode.ACCEPT_EXISTING,
        reason=payload.reason,
    )
    result = await _resolution_service(request).resolve(command)
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
        mode=QuarantineReprocessMode.REJECT,
        reason=reason,
    )
    result = await _resolution_service(request).resolve(command)
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
    "QuarantineRejectPayload",
    "QuarantineReprocessPayload",
    "get_quarantine_record",
    "list_quarantine",
    "reprocess_quarantine_record",
    "accept_existing_quarantine_record",
    "reject_quarantine_record",
    "QuarantineSourceUnitResumePayload",
    "resume_quarantine_source_unit",
    "router",
]
