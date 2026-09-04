"""Runtime persistence and streaming helpers for application-owned source streams."""

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.config.config_health import (
    check_and_refresh_config,
    create_stream_scope_review_packet,
)
from src.domain.ingestion.source_units import SourceUnitMetadata
from src.domain.runtime.models import PartnerRuntimeRunStatus
from src.application.runtime.service import update_runtime_run
from src.core.utils import sanitize_runtime_error
from src.logging import get_structured_logger


# --- Stream Review Gate ---
async def evaluate_stream_mapping(**kwargs: Any):
    """Evaluate mapping health before a staged stream enters ingestion."""
    return await check_and_refresh_config(**kwargs)


async def create_stream_review_packet(**kwargs: Any):
    """Create the review item for a stream with an active mapping."""
    return await create_stream_scope_review_packet(**kwargs)


# --- Stream Staging ---
async def stage_stream_unit(
    raw_page_repo: Any,
    *,
    stage_key: str,
    partner: str,
    fetch_config_id: str,
    source_type: str,
    stream_key: str,
    reconciliation_date: Any,
    unit: Any,
) -> bool:
    """Stage a fetched unit and report whether the adapter supports staging."""
    try:
        await raw_page_repo.stage_from_path(
            stage_key=stage_key,
            partner=partner,
            fetch_config_id=fetch_config_id,
            source_type=source_type,
            stream_key=stream_key,
            reconciliation_date=reconciliation_date,
            unit=unit,
        )
    except TypeError as exc:
        if (
            "must be MotorDatabase" not in str(exc)
            and "can't be used in 'await' expression" not in str(exc)
        ):
            raise
        return False
    return True


# --- Stream Fetching Helpers ---
def checkpoint_result(checkpoint: Any) -> dict[str, Any]:
    status = getattr(checkpoint.status, "value", checkpoint.status)
    return {
        "status": status,
        "currentUnitKey": checkpoint.current_unit_key,
        "lastCompletedUnitKey": checkpoint.last_completed_unit_key,
        "cursorBefore": checkpoint.cursor_before,
        "cursorAfter": checkpoint.cursor_after,
    }


def source_units(
    units: Sequence[SourceUnitMetadata | dict[str, Any]],
) -> list[SourceUnitMetadata]:
    return [SourceUnitMetadata.from_payload(unit) for unit in units]


def unit_high_water_mark(unit: SourceUnitMetadata) -> dict[str, Any]:
    return {
        "sourceUnitKey": unit.source_unit_key,
        "page": unit.page,
        "cursorAfter": unit.cursor_after,
        "contentHash": unit.content_hash,
        "hasMore": unit.has_more,
    }


# --- Stream Runtime Events & Completion ---
def runtime_attempt_event(
    run: Any,
    status: str,
    *,
    result: dict[str, Any] | None = None,
    message: str | None = None,
    stage: str | None = None,
    source_unit_key: str | None = None,
    page: int | None = None,
    duration_ms: float | None = None,
    attempt: int | None = None,
) -> dict[str, Any]:
    """Build a compact, safe event for one application runtime attempt."""

    orchestration = getattr(run, "orchestration", None)
    event: dict[str, Any] = {
        "eventId": str(uuid4()),
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attempt": max(
            1,
            int(
                attempt
                if attempt is not None
                else getattr(orchestration, "try_number", 1)
            ),
        ),
        "stage": stage or (result or {}).get("stage") or status,
        "sourceUnitKey": source_unit_key,
        "page": page,
        "durationMs": max(0.0, float(duration_ms)) if duration_ms is not None else None,
    }
    if orchestration is not None:
        event.update(
            {
                "dagRunId": orchestration.dag_run_id,
                "taskId": orchestration.task_id,
                "mapIndex": orchestration.map_index,
            }
        )
    if result:
        event.update(
            {
                key: result[key]
                for key in (
                    "outcome",
                    "errorCode",
                    "currentPage",
                    "stoppedAt",
                    "fetchedUnitCount",
                    "totalUnitCount",
                )
                if result.get(key) is not None
            }
        )
        if result.get("errorCode") is not None:
            event["errorCode"] = sanitize_runtime_error(result["errorCode"], max_length=96)
        if result.get("stoppedAt") is not None:
            event["unitKey"] = result["stoppedAt"]
        result_stats = result.get("stats")
        if isinstance(result_stats, Mapping):
            for key in (
                "expectedRowCount",
                "actualRowCount",
                "sourceUnitKeys",
                "checkpointFinalized",
            ):
                if result_stats.get(key) is not None:
                    event[key] = result_stats[key]
        result_summary = result.get("stageSummary")
        if isinstance(result_summary, Mapping):
            if not stage and not result.get("stage"):
                event["stage"] = result_summary.get("currentStage") or event["stage"]
            if event.get("durationMs") is None and result_summary.get("durationMs") is not None:
                event["durationMs"] = max(0.0, float(result_summary["durationMs"]))
            event["counters"] = {
                key: result_summary[key]
                for key in (
                    "inputRows",
                    "persistedRows",
                    "rejectedRows",
                    "duplicateRows",
                    "persistenceFailedRows",
                    "quarantinedRows",
                )
                if isinstance(result_summary.get(key), int)
            }
            for key in (
                "inputRows",
                "persistedRows",
                "rejectedRows",
                "duplicateRows",
                "persistenceFailedRows",
                "quarantinedRows",
            ):
                if result_summary.get(key) is not None:
                    event[key] = result_summary[key]
        else:
            quality_counters = result.get("qualityCounters")
            if isinstance(quality_counters, Mapping):
                event["counters"] = dict(quality_counters)
                for key in (
                    "inputRows",
                    "persistedRows",
                    "rejectedRows",
                    "duplicateRows",
                    "persistenceFailedRows",
                    "quarantinedRows",
                ):
                    if quality_counters.get(key) is not None:
                        event[key] = quality_counters[key]
        for key in ("sourceUnitKey", "currentPage", "page", "checkpointBefore", "checkpointAfter"):
            if result.get(key) is not None:
                event[{"currentPage": "page"}.get(key, key)] = result[key]
    if message:
        event["message"] = sanitize_runtime_error(message)
    event = {key: value for key, value in event.items() if value is not None}
    return event


async def finish_source_stream_run(
    *,
    db: Any,
    run: Any,
    partner: str,
    result: dict[str, Any],
    stats: dict[str, int],
    stage_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    duplicate_messages = {
        "FILE_DUPLICATE": "File already processed. Ingestion and reconciliation were skipped safely.",
        "FETCH_UNIT_REPLAY": "Fetch unit already processed. Ingestion and reconciliation were skipped safely.",
        "NO_NEW_FILE": "No new file was found. Ingestion and reconciliation were skipped.",
        "SAFE_DUPLICATE": "This source file was already processed. The retry was skipped safely.",
    }
    waiting_for_review = (
        result.get("outcome") == "WAITING_REVIEW"
        or result.get("waitingForReview") is True
    )
    duplicate_source_outcome = result.get("outcome")
    if result.get("streamAlreadyCompleted"):
        duplicate_source_outcome = "STREAM_ALREADY_COMPLETED"
        result = {
            **result,
            "outcome": "SAFE_DUPLICATE",
            "safeDuplicate": True,
            "duplicateSourceOutcome": duplicate_source_outcome,
        }
    elif duplicate_source_outcome in duplicate_messages:
        result = {
            **result,
            "safeDuplicate": True,
            "duplicateSourceOutcome": duplicate_source_outcome,
        }
    persisted_stats = {**stats, **result}
    finished_at = datetime.now(timezone.utc)
    persisted_stage_summary = dict(
        stage_summary or result.get("stageSummary") or {}
    )
    if result.get("outcome") != "WAITING_REVIEW" and not result.get("waitingForReview"):
        persisted_stage_summary["currentStage"] = "FINALIZING"
    else:
        persisted_stage_summary.setdefault("currentStage", "CONFIGURING")
    persisted_stage_summary.setdefault("stageDurationsMs", {})
    counter_fallbacks = {
        "inputRows": stats.get("totalRows", 0),
        "persistedRows": stats.get("successRows", 0),
        "rejectedRows": stats.get("rejectedRows", 0),
        "duplicateRows": stats.get("duplicateRows", 0),
        "persistenceFailedRows": stats.get("persistenceFailedRows", 0),
        "quarantinedRows": stats.get("quarantinedRows", 0),
    }
    for key, fallback in counter_fallbacks.items():
        if not persisted_stage_summary.get(key) and fallback:
            persisted_stage_summary[key] = fallback
        else:
            persisted_stage_summary.setdefault(key, fallback)
    persisted_stage_summary.setdefault("currentUnitKey", result.get("sourceUnitKey"))
    persisted_stage_summary.setdefault("currentPage", result.get("page"))
    persisted_stage_summary.setdefault("checkpointBefore", result.get("checkpointBefore") or {})
    persisted_stage_summary.setdefault("checkpointAfter", result.get("checkpointAfter") or {})
    persisted_stage_summary.setdefault("startedAt", finished_at.isoformat())
    persisted_stage_summary["finishedAt"] = persisted_stage_summary.get("finishedAt") or finished_at.isoformat()
    if persisted_stage_summary.get("durationMs") is None:
        try:
            started_at = datetime.fromisoformat(persisted_stage_summary["startedAt"])
            persisted_stage_summary["durationMs"] = max(
                0.0, (finished_at - started_at).total_seconds() * 1000
            )
        except (TypeError, ValueError):
            persisted_stage_summary["durationMs"] = 0.0
    if result.get("errorCode"):
        persisted_stage_summary["lastErrorCode"] = sanitize_runtime_error(
            result["errorCode"], max_length=96
        )
    if result.get("error"):
        persisted_stage_summary["lastError"] = sanitize_runtime_error(result["error"])
    safe_message = sanitize_runtime_error(result.get("error")) if result.get("error") else None

    safe_duplicate = bool(result.get("safeDuplicate"))
    partial = (
        not safe_duplicate
        and result.get("outcome") == "PARTIAL"
    ) or (
        not safe_duplicate
        and any(
            int(persisted_stage_summary.get(key, 0) or 0) > 0
            for key in ("rejectedRows", "persistenceFailedRows", "quarantinedRows")
        )
    )

    async def persist(
        *,
        status: PartnerRuntimeRunStatus,
        message: str,
        event_status: str,
    ) -> None:
        try:
            await update_runtime_run(
                db,
                str(run.id),
                status=status,
                message=message,
                stats=persisted_stats,
                stage_summary=persisted_stage_summary,
                finished_at=finished_at,
                attempt_event=runtime_attempt_event(
                    run,
                    event_status,
                    result={**result, "stageSummary": persisted_stage_summary},
                    message=message,
                    stage=persisted_stage_summary.get("currentStage"),
                    source_unit_key=persisted_stage_summary.get("currentUnitKey"),
                    page=persisted_stage_summary.get("currentPage"),
                    duration_ms=persisted_stage_summary.get("durationMs"),
                ),
            )
        except Exception:
            get_structured_logger().emit_ingestion_observability_write_failed(
                run_id=str(run.id),
                source_file_id=(
                    persisted_stage_summary.get("sourceFileId")
                    or result.get("sourceFileId")
                    or getattr(run, "source_file_id", None)
                ),
                partner=partner,
                stage=persisted_stage_summary.get("currentStage"),
            )

    if waiting_for_review:
        terminal_status = PartnerRuntimeRunStatus.WAITING_REVIEW
        await persist(
            status=terminal_status,
            message=safe_message
            or "A draft mapping is waiting for review before ingestion can continue.",
            event_status=terminal_status.value,
        )
    elif result.get("success"):
        terminal_status = (
            PartnerRuntimeRunStatus.PARTIAL
            if partial
            else PartnerRuntimeRunStatus.COMPLETED
        )
        await persist(
            status=terminal_status,
            message=duplicate_messages.get(
                str(result.get("outcome") or ""),
                "Sequential source-unit ingestion completed with rejected records."
                if partial
                else "Sequential source-unit ingestion completed successfully.",
            ),
            event_status=terminal_status.value,
        )
    else:
        terminal_status = PartnerRuntimeRunStatus.FAILED
        await persist(
            status=terminal_status,
            message=safe_message or "Source-unit ingestion failed.",
            event_status=terminal_status.value,
        )
    return {
        "success": result.get("success", False),
        "stage": "ingestion" if result.get("processed", 0) else "fetch",
        "partner": partner,
        **result,
        "stageSummary": persisted_stage_summary,
        "stats": persisted_stats,
        "runtimeRun": {
            "id": str(run.id),
            "status": (
                PartnerRuntimeRunStatus.WAITING_REVIEW.value
                if waiting_for_review
                else PartnerRuntimeRunStatus.PARTIAL.value
                if partial and result.get("success")
                else PartnerRuntimeRunStatus.COMPLETED.value
                if result.get("success")
                else PartnerRuntimeRunStatus.FAILED.value
            ),
            "outcome": result.get("outcome"),
            "stageSummary": persisted_stage_summary,
        },
    }


__all__ = [
    "evaluate_stream_mapping",
    "create_stream_review_packet",
    "stage_stream_unit",
    "checkpoint_result",
    "source_units",
    "unit_high_water_mark",
    "runtime_attempt_event",
    "finish_source_stream_run",
]
