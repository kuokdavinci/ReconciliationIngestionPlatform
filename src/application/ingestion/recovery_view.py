"""Application read model for operator recovery visibility."""

from datetime import datetime
import re
from collections.abc import Mapping, Sequence
from typing import Any

from src.domain.ingestion.checkpoints import (
    CheckpointStatus,
    IngestionCheckpoint,
    SourceUnitStatus,
    SourceUnitSummary,
)

_REPLAY_OUTCOMES = {"FILE_DUPLICATE", "FETCH_UNIT_REPLAY", "NO_NEW_FILE", "SAFE_DUPLICATE"}
_ACTIVE_RUNTIME_STATUSES = {
    "QUEUED",
    "FETCHING",
    "INGESTING",
    "RUNNING",
    "WAITING_RECONCILE",
    "RECONCILING",
}
_SENSITIVE_ERROR_PATTERN = re.compile(
    r"(?i)\b(password|passwd|token|secret|api[_-]?key|authorization)\b"
    r"\s*[:=]\s*(?:bearer\s+)?[^\s,;]+"
)
_CREDENTIAL_URL_PATTERN = re.compile(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _safe_error(value: str | None) -> str | None:
    if not value:
        return None
    text = _CREDENTIAL_URL_PATTERN.sub(r"\1[REDACTED]@", str(value))
    text = _SENSITIVE_ERROR_PATTERN.sub("\\1=[REDACTED]", text)
    return text[:220].rstrip() + ("..." if len(text) > 220 else "")


def _serialize_unit(unit: SourceUnitSummary) -> dict[str, Any]:
    data = unit.model_dump(by_alias=True)
    data["status"] = unit.status.value
    data["lastError"] = _safe_error(unit.last_error)
    for key in ("nextRetryAt", "startedAt", "completedAt", "updatedAt"):
        value = data.get(key)
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return data


def _latest_run_status(latest_run: Mapping[str, Any] | None) -> str | None:
    if not latest_run:
        return None
    status = latest_run.get("status")
    if status is None:
        return None
    return status.value if hasattr(status, "value") else str(status)


def _duplicate_count(latest_run: Mapping[str, Any] | None) -> int:
    stats = (latest_run or {}).get("stats") or {}
    for key in ("duplicateRows", "duplicateCount", "duplicates"):
        value = stats.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return max(value, 0)
    return 0


def _recovery_events(
    units: list[SourceUnitSummary],
    resolution_metadata: Mapping[str, Any] | None,
    persisted_events: Sequence[Mapping[str, Any]] | None = None,
    attempt_history: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    event_ids: set[str] = set()

    def append_event(raw_event: Mapping[str, Any], *, default_status: str | None = None) -> None:
        event = dict(raw_event)
        timestamp = event.get("timestamp")
        if isinstance(timestamp, datetime):
            event["timestamp"] = timestamp.isoformat()
        event_id = str(event.get("eventId") or "")
        if not event_id or not event.get("timestamp") or event_id in event_ids:
            return
        event_ids.add(event_id)
        if default_status is not None:
            event.setdefault("status", default_status)
        if event.get("message") is not None:
            event["message"] = _safe_error(str(event["message"]))
        if event.get("reason") is not None:
            event["reason"] = _safe_error(str(event["reason"]))
        events.append(event)

    for persisted in persisted_events or []:
        append_event(persisted)

    for attempt in attempt_history or []:
        append_event(attempt, default_status="RUNTIME")

    if events:
        return sorted(events, key=lambda event: str(event.get("timestamp") or ""))

    for unit in units:
        if unit.started_at is not None:
            events.append({
                "eventId": f"{unit.unit_key}:PROCESSING",
                "unitKey": unit.unit_key,
                "status": SourceUnitStatus.PROCESSING.value,
                "timestamp": _iso(unit.started_at),
            })
        if unit.completed_at is not None:
            events.append({
                "eventId": f"{unit.unit_key}:{unit.status.value}:COMPLETED",
                "unitKey": unit.unit_key,
                "status": unit.status.value,
                "timestamp": _iso(unit.completed_at),
            })
        elif unit.status != SourceUnitStatus.PROCESSING:
            events.append({
                "eventId": f"{unit.unit_key}:{unit.status.value}",
                "unitKey": unit.unit_key,
                "status": unit.status.value,
                "timestamp": _iso(unit.updated_at),
                "errorCode": unit.error_code,
                "message": _safe_error(unit.last_error),
            })

    metadata = resolution_metadata or {}
    if metadata.get("action") and metadata.get("resolvedAt"):
        resolved_at = metadata["resolvedAt"]
        if isinstance(resolved_at, datetime):
            resolved_at = resolved_at.isoformat()
        events.append({
            "eventId": "resolution",
            "status": "RESOLVED",
            "action": str(metadata["action"]),
            "timestamp": str(resolved_at),
            "actor": str(metadata.get("operatorId") or "system"),
            "reason": _safe_error(str(metadata.get("reason") or "")),
        })

    return sorted(events, key=lambda event: event.get("timestamp") or "")


def _annotate_request_attempts(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Attach a stable request number to every recovery event.

    Airflow retry events may carry ``attempt`` while the manual
    ``RETRY_REQUESTED`` event does not. The operator still needs one coherent
    sequence, so infer the missing number from the chronological event stream.
    """

    request_attempt = 0
    for event in events:
        raw_attempt = event.get("attempt")
        try:
            explicit_attempt = int(raw_attempt) if raw_attempt is not None else 0
        except (TypeError, ValueError):
            explicit_attempt = 0
        if explicit_attempt > 0:
            request_attempt = max(request_attempt, explicit_attempt)
        elif str(event.get("status") or "").upper() == "RETRY_REQUESTED":
            request_attempt = max(request_attempt + 1, 1)
        elif request_attempt == 0:
            request_attempt = 1
        event["requestAttempt"] = request_attempt
    return events, request_attempt


def _safe_stream_key(checkpoint: IngestionCheckpoint | None) -> str | None:
    if checkpoint is None:
        return None
    return f"{checkpoint.partner}:{checkpoint.source_type}:{checkpoint.mode.value.lower()}"


def _recovery_status(
    checkpoint: IngestionCheckpoint | None,
    latest_run: Mapping[str, Any] | None,
) -> str:
    latest_status = _latest_run_status(latest_run)
    stats = (latest_run or {}).get("stats") or {}
    outcome = stats.get("outcome")
    if latest_status == "COMPLETED" and outcome in _REPLAY_OUTCOMES:
        return "REPLAYED"
    if latest_status == "WAITING_REVIEW":
        return "WAITING_REVIEW"
    if checkpoint is not None:
        if checkpoint.status == CheckpointStatus.BLOCKED:
            return "BLOCKED"
        if checkpoint.status == CheckpointStatus.FAILED:
            return "FAILED"
        if checkpoint.status == CheckpointStatus.PROCESSING:
            return "PROCESSING"
        if (
            checkpoint.status == CheckpointStatus.DISCOVERED
            and (checkpoint.resolution_metadata or {}).get("action") == "SKIP"
        ):
            return "PENDING"
    if checkpoint is not None and latest_status == "COMPLETED":
        return "COMPLETED"
    if latest_status in _ACTIVE_RUNTIME_STATUSES:
        return "PROCESSING"
    return latest_status or "IDLE"


def _unit_by_key(
    units: list[SourceUnitSummary],
    unit_key: str | None,
) -> SourceUnitSummary | None:
    if unit_key is None:
        return None
    return next((unit for unit in units if unit.unit_key == unit_key), None)


def build_recovery_view(
    *,
    checkpoint: IngestionCheckpoint | None,
    latest_run: Mapping[str, Any] | None,
    max_attempts: int,
    expected_unit_count: int | None = None,
    attempt_history: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a safe recovery payload without exposing checkpoint internals."""

    units = checkpoint.unit_timeline if checkpoint is not None else []
    current_unit = _unit_by_key(
        units,
        checkpoint.current_unit_key if checkpoint is not None else None,
    )
    last_completed_unit = _unit_by_key(
        units,
        checkpoint.last_completed_unit_key if checkpoint is not None else None,
    )
    status = _recovery_status(checkpoint, latest_run)
    fallback_unit = current_unit or last_completed_unit or next(
        (
            unit
            for unit in units
            if unit.status
            in {
                SourceUnitStatus.FAILED,
                SourceUnitStatus.BLOCKED,
                SourceUnitStatus.WAITING_REVIEW,
                SourceUnitStatus.PROCESSING,
            }
        ),
        None,
    )
    stream_metadata = checkpoint.stream_metadata if checkpoint is not None else {}
    latest_stats = (latest_run or {}).get("stats") or {}
    current_page = (
        current_unit.page
        if current_unit is not None
        else stream_metadata.get("page")
        or (fallback_unit.page if fallback_unit is not None else None)
        or (latest_stats.get("currentPage") if isinstance(latest_stats.get("currentPage"), int) else None)
    )
    error_code = (
        checkpoint.error_code
        if checkpoint is not None and checkpoint.error_code is not None
        else (fallback_unit.error_code if fallback_unit is not None else None)
    )
    last_error = (
        checkpoint.last_error
        if checkpoint is not None and checkpoint.last_error is not None
        else (fallback_unit.last_error if fallback_unit is not None else None)
    )
    runtime_retryable = latest_stats.get("retryable")
    retryable = (
        checkpoint.retryable
        if checkpoint is not None and checkpoint.retryable is not None
        else fallback_unit.retryable
        if fallback_unit is not None and fallback_unit.retryable is not None
        else runtime_retryable
        if isinstance(runtime_retryable, bool)
        else None
    )
    if (
        checkpoint is not None
        and (checkpoint.resolution_metadata or {}).get("action") == "SKIP"
    ):
        retryable = False
    next_retry_at = (
        checkpoint.next_retry_at
        if checkpoint is not None and checkpoint.next_retry_at is not None
        else (fallback_unit.next_retry_at if fallback_unit is not None else None)
    )
    total_unit_count = max(
        len(units),
        expected_unit_count or 0,
        latest_stats.get("totalUnitCount", 0)
        if isinstance(latest_stats.get("totalUnitCount", 0), int)
        else 0,
    )
    fetched_unit_count = latest_stats.get("fetchedUnitCount", 0)
    if not isinstance(fetched_unit_count, int):
        fetched_unit_count = 0
    fetched_unit_count = min(max(fetched_unit_count, 0), total_unit_count)
    events, request_attempt_count = _annotate_request_attempts(
        _recovery_events(
            units,
            checkpoint.resolution_metadata if checkpoint is not None else None,
            checkpoint.recovery_events if checkpoint is not None else None,
            [
                *(attempt_history or []),
                *((latest_run or {}).get("attemptHistory") or []),
            ],
        )
    )
    duplicate_message = (
        latest_run.get("message")
        if latest_run is not None
        and (
            latest_stats.get("safeDuplicate") is True
            or latest_stats.get("outcome") in _REPLAY_OUTCOMES
        )
        else None
    )
    return {
        "status": status,
        "streamKey": _safe_stream_key(checkpoint),
        "mode": checkpoint.mode.value if checkpoint is not None else "SCHEDULED",
        "lastCompletedUnitKey": checkpoint.last_completed_unit_key if checkpoint else None,
        "currentUnitKey": checkpoint.current_unit_key if checkpoint else None,
        "currentPage": current_page,
        "cursorBefore": (
            checkpoint.cursor_before
            if checkpoint is not None and checkpoint.cursor_before is not None
            else (fallback_unit.cursor_before if fallback_unit is not None else None)
        ),
        "attemptCount": max(
            checkpoint.attempt_count if checkpoint is not None else 0,
            fallback_unit.attempt_count if fallback_unit is not None else 0,
        ),
        "maxAttempts": max_attempts,
        "requestAttemptCount": request_attempt_count,
        "retryable": retryable,
        "nextRetryAt": _iso(next_retry_at),
        "errorCode": error_code,
        "lastError": _safe_error(last_error),
        "units": [_serialize_unit(unit) for unit in units],
        "completedUnitCount": sum(
            unit.status
            in {
                SourceUnitStatus.COMPLETED,
                SourceUnitStatus.SKIPPED,
                SourceUnitStatus.REPLAYED,
            }
            for unit in units
        ),
        "fetchedUnitCount": fetched_unit_count,
        "totalUnitCount": total_unit_count,
        "duplicateCount": _duplicate_count(latest_run),
        "safeDuplicate": latest_stats.get("safeDuplicate") is True or latest_stats.get("outcome") in _REPLAY_OUTCOMES,
        "duplicateSourceOutcome": latest_stats.get("duplicateSourceOutcome") or (
            latest_stats.get("outcome") if latest_stats.get("outcome") in _REPLAY_OUTCOMES else None
        ),
        "duplicateMessage": duplicate_message,
        "events": events,
    }
