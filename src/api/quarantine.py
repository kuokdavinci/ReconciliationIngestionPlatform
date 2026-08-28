"""Bounded quarantine query and operator-action endpoints."""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
import inspect
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from src.api.actor import require_actor
from src.api.dependencies import get_request_db as _get_db
from src.application.audit.service import record_audit_event
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
    QuarantineIssueType,
    QuarantinePriority,
    QuarantineQuery,
    QuarantineStatus,
    quarantine_issue_type_for_error_code,
    sanitize_raw_row,
)
from src.infrastructure.ingestion.composition import build_quarantine_resolution_service
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.infrastructure.partner_transaction.repository import DataContainerRepository
from src.infrastructure.ingestion.quarantine_repository import IngestionQuarantineRepository
from src.pipeline.quality_gate import REQUIRED_SCHEMA_PATHS


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
    action_id: str = Field(alias="actionId", min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=500)


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


_EVIDENCE_FIELD_LIMIT = 20
_OBSERVED_COLUMN_LIMIT = 50
_SAFE_DUPLICATE_FIELDS = ("id", "trace", "amount", "currency", "status")
_SENSITIVE_FIELD_TOKENS = (
    "password",
    "secret",
    "token",
    "apikey",
    "authorization",
    "credential",
    "fingerprint",
)


def _is_sensitive_field(name: str) -> bool:
    normalized = "".join(character for character in name.lower() if character.isalnum())
    return any(token in normalized for token in _SENSITIVE_FIELD_TOKENS)


def _evidence_value(value: Any) -> Any:
    """Return a bounded display value without exposing parsed timestamps."""

    if value is None:
        return None
    if hasattr(value, "isoformat") and not isinstance(value, (str, bytes)):
        return "[TIMESTAMP_UNAVAILABLE]"
    return _bounded_value(sanitize_raw_row(value), drop_sensitive=True)


def _mapping_source(mapping: Any) -> str | None:
    source = getattr(mapping, "sourceField", None)
    return str(source) if source else None


def _mapping_path(mapping: Any) -> str | None:
    path = getattr(mapping, "path", None)
    return str(path) if path else None


def _mapping_column(mapping: Any) -> int | str | None:
    column = getattr(mapping, "column", None)
    if isinstance(column, (int, str)):
        return column
    return None


def _mapping_by_source(mappings: list[Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for mapping in mappings:
        path = _mapping_path(mapping)
        source = _mapping_source(mapping)
        if path:
            result[path.lower()] = mapping
        if source:
            result[source.lower()] = mapping
    return result


def _mapping_by_column(mappings: list[Any]) -> dict[str, Any]:
    return {
        str(column): mapping
        for mapping in mappings
        if (column := _mapping_column(mapping)) is not None
    }


def _error_fields(record: IngestionQuarantineRecord) -> set[str]:
    fields: set[str] = set()
    for error in record.errors:
        for key in ("field", "fieldName", "path", "sourceField"):
            value = error.get(key) if isinstance(error, Mapping) else None
            if isinstance(value, str) and value:
                fields.add(value.lower())
    return fields


def _sample_state(field_name: str, canonical_path: str | None, value: Any, error_fields: set[str]) -> str:
    flagged = field_name.lower() in error_fields or (
        canonical_path is not None and canonical_path.lower() in error_fields
    )
    if not flagged:
        return "OK"
    return "MISSING" if value is None or (isinstance(value, str) and not value.strip()) else "INVALID"


def _sample_fields(record: IngestionQuarantineRecord, config: Any | None) -> list[dict[str, Any]]:
    raw_row = record.raw_row
    mappings = list(getattr(config, "field_mappings", None) or [])
    by_source = _mapping_by_source(mappings)
    by_column = _mapping_by_column(mappings)
    error_fields = _error_fields(record)
    fields: list[dict[str, Any]] = []

    if isinstance(raw_row, Mapping):
        for key, value in list(raw_row.items())[:_EVIDENCE_FIELD_LIMIT]:
            source_field = str(key)
            if _is_sensitive_field(source_field):
                continue
            mapping = by_source.get(source_field.lower())
            canonical_path = _mapping_path(mapping) if mapping is not None else None
            fields.append(
                {
                    "sourceField": source_field,
                    "canonicalPath": canonical_path,
                    "column": _mapping_column(mapping) if mapping is not None else None,
                    "value": _evidence_value(value),
                    "state": _sample_state(source_field, canonical_path, value, error_fields),
                }
            )
    elif isinstance(raw_row, (list, tuple)):
        for index, value in enumerate(raw_row[:_EVIDENCE_FIELD_LIMIT], start=1):
            mapping = by_column.get(str(index))
            canonical_path = _mapping_path(mapping) if mapping is not None else None
            mapped_source_field = _mapping_source(mapping) if mapping is not None else None
            display_source_field = mapped_source_field or f"Column {index}"
            if _is_sensitive_field(display_source_field):
                continue
            fields.append(
                {
                    "sourceField": display_source_field,
                    "canonicalPath": canonical_path,
                    "column": _mapping_column(mapping) if mapping is not None else index,
                    "value": _evidence_value(value),
                    "state": _sample_state(display_source_field, canonical_path, value, error_fields),
                }
            )

    present = {
        str(field.get("canonicalPath") or field.get("sourceField") or "").lower()
        for field in fields
    }
    for mapping in mappings:
        path = _mapping_path(mapping)
        source = _mapping_source(mapping) or path
        if not path or not source or path.lower() not in error_fields and source.lower() not in error_fields:
            continue
        if path.lower() in present or source.lower() in present:
            continue
        fields.append(
            {
                "sourceField": source,
                "canonicalPath": path,
                "column": _mapping_column(mapping),
                "value": None,
                "state": "MISSING",
            }
        )
        if len(fields) >= _EVIDENCE_FIELD_LIMIT:
            break
    for field in sorted(error_fields):
        if len(fields) >= _EVIDENCE_FIELD_LIMIT or field in present or _is_sensitive_field(field):
            continue
        fields.append(
            {
                "sourceField": field,
                "canonicalPath": field,
                "column": None,
                "value": None,
                "state": "MISSING",
            }
        )
    return fields[:_EVIDENCE_FIELD_LIMIT]


def _mapping_state(mapping: Any, raw_row: Any, observed_columns: list[str] | None) -> str:
    source = _mapping_source(mapping)
    if observed_columns is not None and source:
        return "PRESENT" if source in observed_columns else "MISSING"
    column = _mapping_column(mapping)
    if isinstance(raw_row, (list, tuple)) and column is not None:
        try:
            index = int(column)
        except (TypeError, ValueError):
            return "UNKNOWN"
        return "PRESENT" if 1 <= index <= len(raw_row) else "MISSING"
    return "UNKNOWN"


def _mapping_evidence(record: IngestionQuarantineRecord, config: Any | None) -> dict[str, Any] | None:
    if config is None:
        return None
    raw_row = record.raw_row
    observed_columns: list[str] | None = None
    if isinstance(raw_row, Mapping):
        observed_columns = [
            str(key)
            for key in list(raw_row.keys())[:_OBSERVED_COLUMN_LIMIT]
            if not _is_sensitive_field(str(key))
        ]
    mappings = list(getattr(config, "field_mappings", None) or [])
    required_fields: list[dict[str, Any]] = []
    for mapping in mappings:
        path = _mapping_path(mapping)
        if not path or not (getattr(mapping, "required", False) or path in REQUIRED_SCHEMA_PATHS):
            continue
        required_fields.append(
            {
                "canonicalPath": path,
                "sourceField": _mapping_source(mapping),
                "column": _mapping_column(mapping),
                "type": str(getattr(getattr(mapping, "type", None), "value", getattr(mapping, "type", "STRING"))),
                "state": _mapping_state(mapping, raw_row, observed_columns),
            }
        )
        if len(required_fields) >= _EVIDENCE_FIELD_LIMIT:
            break
    return {
        "configVersion": getattr(config, "config_version", None),
        "requiredFields": required_fields,
        "observedColumns": observed_columns,
    }


def _issue_summary(record: IngestionQuarantineRecord) -> str:
    code = next((code for code in (_error_code(error) for error in record.errors) if code), None)
    field = next(iter(sorted(_error_fields(record))), None)
    reason = " ".join(
        str(error.get("reason", ""))
        for error in record.errors
        if isinstance(error, Mapping)
    ).lower()
    if field and (code == "MISSING_REQUIRED_FIELD" or "missing" in reason or "not found" in reason):
        return f"Missing {field.rsplit('.', 1)[-1]}"
    return {
        "CONFLICTING_DUPLICATE": "Conflict duplicate",
        "EQUIVALENT_DUPLICATE": "Exact duplicate",
        "INVALID_TIMESTAMP": "Invalid timestamp",
    }.get(code or "", (code or "Quarantined row").replace("_", " ").title())


def _incoming_duplicate_fields(sample_fields: list[dict[str, Any]]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field in sample_fields:
        canonical = str(field.get("canonicalPath") or field.get("sourceField") or "")
        normalized = canonical.rsplit(".", 1)[-1]
        if normalized in _SAFE_DUPLICATE_FIELDS:
            values[normalized] = field.get("value")
    return values


def _existing_duplicate_fields(existing: Any) -> dict[str, Any]:
    partner_data = getattr(existing, "partner_data", None)
    if partner_data is None:
        return {}
    return {
        "id": _evidence_value(getattr(partner_data, "id", None)),
        "trace": _evidence_value(getattr(partner_data, "trace", None)),
        "amount": _evidence_value(getattr(partner_data, "amount", None)),
        "currency": _evidence_value(getattr(partner_data, "currency", None)),
        "status": _evidence_value(getattr(partner_data, "status", None)),
    }


def _duplicate_field_matches(name: str, incoming: Any, existing: Any) -> bool:
    if name == "amount":
        try:
            return Decimal(str(incoming)) == Decimal(str(existing))
        except (InvalidOperation, ValueError):
            pass
    return str(incoming) == str(existing)


async def _duplicate_evidence(
    db: Any,
    record: IngestionQuarantineRecord,
    sample_fields: list[dict[str, Any]],
) -> dict[str, Any]:
    incoming = _incoming_duplicate_fields(sample_fields)
    existing: dict[str, Any] = {}
    if record.ingestion_key:
        try:
            current = await DataContainerRepository(db).find_by_ingestion_key(
                record.partner,
                record.ingestion_key,
            )
            if current is not None:
                existing = _existing_duplicate_fields(current)
        except Exception:
            existing = {}

    if not existing:
        return {
            "status": "UNAVAILABLE",
            "fields": [
                {
                    "name": name,
                    "incoming": incoming.get(name),
                    "existing": None,
                    "result": "UNAVAILABLE",
                }
                for name in _SAFE_DUPLICATE_FIELDS
            ],
        }

    fields = []
    for name in _SAFE_DUPLICATE_FIELDS:
        incoming_value = incoming.get(name)
        existing_value = existing.get(name)
        result = (
            "UNAVAILABLE"
            if incoming_value is None or existing_value is None
            else "MATCH"
            if _duplicate_field_matches(name, incoming_value, existing_value)
            else "DIFF"
        )
        fields.append(
            {
                "name": name,
                "incoming": incoming_value,
                "existing": existing_value,
                "result": result,
            }
        )
    return {
        "status": "EQUIVALENT" if all(field["result"] == "MATCH" for field in fields) else "CONFLICT",
        "fields": fields,
    }


async def _quarantine_evidence(db: Any, record: IngestionQuarantineRecord) -> dict[str, Any]:
    error_codes = [code for code in (_error_code(error) for error in record.errors) if code]
    issue_type = quarantine_issue_type_for_error_code(error_codes[0] if error_codes else None)
    config = None
    if record.config_version:
        try:
            config = await MappingConfigRepository(db).find_by_version(
                record.partner,
                record.config_version,
            )
        except Exception:
            config = None
    sample_fields = _sample_fields(record, config)
    evidence: dict[str, Any] = {"sampleFields": sample_fields}
    mapping = _mapping_evidence(record, config)
    if mapping is not None:
        evidence["mapping"] = mapping
    if issue_type is QuarantineIssueType.DUPLICATE:
        evidence["duplicate"] = await _duplicate_evidence(db, record, sample_fields)
    return evidence


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
        "reviewPacketId": payload.get("reviewPacketId"),
        "postApprovalRunId": payload.get("postApprovalRunId"),
        "quarantineGroupKey": (
            payload.get("postApprovalRunId")
            or payload.get("reviewPacketId")
            or payload["sourceFileId"]
        ),
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
        "lastActionActor": (
            record.resolution_history[-1].actor
            if record.resolution_history
            else None
        ),
        "lastActionAt": (
            record.resolution_history[-1].timestamp.isoformat()
            if record.resolution_history
            else None
        ),
        "priority": payload.get("priority"),
        "reviewDueAt": payload.get("reviewDueAt"),
        "escalationLevel": payload.get("escalationLevel", 0),
        "escalatedAt": payload.get("escalatedAt"),
        "escalatedBy": payload.get("escalatedBy"),
        "lastActionId": payload.get("lastActionId"),
        "errorCodes": [code for code in (_error_code(error) for error in record.errors) if code],
        "issueType": quarantine_issue_type_for_error_code(
            next((code for code in (_error_code(error) for error in record.errors) if code), None)
        ).value,
        "issueSummary": _issue_summary(record),
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
        "CLAIM_EXPIRED",
        "ACTION_IN_PROGRESS",
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


async def _action_response(
    request: Request,
    result: QuarantineResolutionResult,
) -> dict[str, Any]:
    """Return the action; packet reconciliation is an explicit operator step."""
    return _result_payload(result)


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
    review_packet_id: str | None = Query(default=None, alias="reviewPacketId"),
    post_approval_run_id: str | None = Query(default=None, alias="postApprovalRunId"),
    claimed_by: str | None = Query(default=None, alias="claimedBy"),
    priority: QuarantinePriority | None = Query(default=None),
    issue_type: QuarantineIssueType | None = Query(default=None, alias="issueType"),
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
    review_packet_id_value = review_packet_id if isinstance(review_packet_id, str) else None
    post_approval_run_id_value = post_approval_run_id if isinstance(post_approval_run_id, str) else None
    claimed_by_value = claimed_by if isinstance(claimed_by, str) else None
    priority_value = priority if isinstance(priority, QuarantinePriority) else None
    issue_type_value = issue_type if isinstance(issue_type, QuarantineIssueType) else None
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
        reviewPacketId=review_packet_id_value,
        postApprovalRunId=post_approval_run_id_value,
        claimedBy=claimed_by_value,
        priority=priority_value,
        issueType=issue_type_value,
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
    response = {
        "items": [_bounded_record(record) for record in records],
        "nextCursor": next_cursor,
        "limit": limit_value,
        "summary": summary,
    }
    group_call = getattr(repository, "group_summaries", None)
    if callable(group_call):
        group_value = group_call(query)
        if inspect.isawaitable(group_value):
            group_value = await group_value
        if isinstance(group_value, list):
            response["groups"] = group_value
    return response


@router.get("/{record_id}")
async def get_quarantine_record(request: Request, record_id: str):
    record = await IngestionQuarantineRepository(_get_db(request)).find_by_id(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Quarantine record not found.")
    result = _bounded_record(record, include_evidence=True)
    result["evidence"] = await _quarantine_evidence(_get_db(request), record)
    return result


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
    return await _action_response(request, result)


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
    return await _action_response(request, result)


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
    return await _action_response(request, result)


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
    return await _action_response(request, result)


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
            action_id=payload.action_id,
            audit_recorder=lambda **kwargs: record_audit_event(_get_db(request), **kwargs),
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
