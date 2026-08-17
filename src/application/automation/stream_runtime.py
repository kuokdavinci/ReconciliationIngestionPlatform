"""Runtime persistence and streaming helpers for application-owned source streams."""

from collections.abc import Sequence
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
) -> dict[str, Any]:
    """Build a compact, safe event for one application runtime attempt."""

    orchestration = getattr(run, "orchestration", None)
    event: dict[str, Any] = {
        "eventId": str(uuid4()),
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attempt": getattr(orchestration, "try_number", 1),
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
        if result.get("stoppedAt") is not None:
            event["unitKey"] = result["stoppedAt"]
    if message:
        event["message"] = message
    return event


async def finish_source_stream_run(
    *,
    db: Any,
    run: Any,
    partner: str,
    result: dict[str, Any],
    stats: dict[str, int],
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
    if waiting_for_review:
        terminal_status = PartnerRuntimeRunStatus.WAITING_REVIEW
        await update_runtime_run(
            db,
            str(run.id),
            status=terminal_status,
            message=result.get("error")
            or "A draft mapping is waiting for review before ingestion can continue.",
            stats=persisted_stats,
            finished_at=datetime.now(timezone.utc),
            attempt_event=runtime_attempt_event(
                run,
                terminal_status.value,
                result=result,
                message=result.get("error"),
            ),
        )
    elif result.get("success"):
        terminal_status = PartnerRuntimeRunStatus.COMPLETED
        await update_runtime_run(
            db,
            str(run.id),
            status=terminal_status,
            message=duplicate_messages.get(
                str(result.get("outcome") or ""),
                "Sequential source-unit ingestion completed successfully.",
            ),
            stats=persisted_stats,
            finished_at=datetime.now(timezone.utc),
            attempt_event=runtime_attempt_event(
                run,
                terminal_status.value,
                result=result,
                message="Sequential source-unit ingestion completed successfully.",
            ),
        )
    else:
        terminal_status = PartnerRuntimeRunStatus.FAILED
        await update_runtime_run(
            db,
            str(run.id),
            status=terminal_status,
            message=result.get("error") or "Source-unit ingestion failed.",
            stats=persisted_stats,
            finished_at=datetime.now(timezone.utc),
            attempt_event=runtime_attempt_event(
                run,
                terminal_status.value,
                result=result,
                message=result.get("error"),
            ),
        )
    return {
        "success": result.get("success", False),
        "stage": "ingestion" if result.get("processed", 0) else "fetch",
        "partner": partner,
        **result,
        "stats": persisted_stats,
        "runtimeRun": {
            "id": str(run.id),
            "status": (
                PartnerRuntimeRunStatus.WAITING_REVIEW.value
                if waiting_for_review
                else PartnerRuntimeRunStatus.COMPLETED.value
                if result.get("success")
                else PartnerRuntimeRunStatus.FAILED.value
            ),
            "outcome": result.get("outcome"),
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
