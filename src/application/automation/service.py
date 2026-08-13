"""Application entrypoint for one configured ingestion stream."""

from collections.abc import Awaitable, Callable
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.application.automation.contracts import (
    ExecuteStreamCommand,
    ExecuteStreamOutcome,
    ExecuteStreamResult,
)
from src.application.automation.stream_identity import stream_identity
from src.infrastructure.fetch_config.repository import FetchConfigRepository
from src.infrastructure.ingestion.checkpoint_repository import IngestionCheckpointRepository
from src.domain.runtime.models import PartnerRuntimeRunStatus
from src.services.runtime_runs import update_runtime_run

BUSINESS_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
StreamRunner = Callable[..., Awaitable[dict[str, Any]]]


async def execute_stream(
    command: ExecuteStreamCommand,
    *,
    db: Any,
    config_loader: Any,
    fetch_config_repository: FetchConfigRepository | None = None,
    checkpoint_repository: Any = None,
    runner: StreamRunner | None = None,
    batch_size: int = 100,
    structured_logger: Any = None,
) -> ExecuteStreamResult:
    """Load and execute exactly one fetch configuration."""

    repository = fetch_config_repository or FetchConfigRepository(db)
    config = await repository.find_by_id(command.fetch_config_id)
    try:
        if config is None:
            raise ValueError(f"fetch config '{command.fetch_config_id}' was not found")
        if config.partner != command.partner:
            raise ValueError("fetch config partner changed")
        if str(config.updated_at) != command.config_version:
            raise ValueError("fetch config version changed")
    except ValueError as exc:
        if command.runtime_run_id is not None:
            await update_runtime_run(
                db,
                str(command.runtime_run_id),
                status=PartnerRuntimeRunStatus.FAILED,
                message=str(exc),
                stats={
                    "errorCode": "CONFIG_VERSION_CHANGED"
                    if "version" in str(exc)
                    else "FETCH_CONFIG_INVALID",
                    "retryable": False,
                },
                finished_at=datetime.now(timezone.utc),
            )
        raise

    if runner is None:
        from src.scheduler.jobs import run_fetch_config_once

        runner = run_fetch_config_once

    reconciliation_day = command.reconciliation_date
    if reconciliation_day is None:
        raise ValueError("reconciliation_date is required for stream execution")

    reconciliation_date = datetime.combine(
        reconciliation_day,
        time.min,
        tzinfo=BUSINESS_TIMEZONE,
    )
    raw_result = await runner(
        config=config,
        db=db,
        config_loader=config_loader,
        reconciliation_date=reconciliation_date,
        batch_size=batch_size,
        structured_logger=structured_logger,
        mode=command.mode,
        runtime_run_id=command.runtime_run_id,
        orchestration=_orchestration_payload(command),
        mapping_config_version=command.mapping_version,
        backfill_run_id=command.backfill_run_id,
        raise_on_unexpected=True,
    )
    result = _normalize_result(raw_result)
    checkpoint_repository = checkpoint_repository or IngestionCheckpointRepository(db)
    checkpoint = await _find_checkpoint(
        checkpoint_repository,
        config,
        command,
        reconciliation_date,
    )
    return _apply_checkpoint(result, checkpoint)


def _orchestration_payload(command: ExecuteStreamCommand) -> dict[str, Any] | None:
    if command.orchestration is None:
        return None
    payload = command.orchestration.model_dump(by_alias=True, mode="json")
    payload["correlationId"] = command.correlation_id
    return payload


async def _find_checkpoint(repository, config, command, reconciliation_date):
    identity = stream_identity(
        config,
        mode=command.mode,
        reconciliation_date=reconciliation_date,
    )
    return await repository.find_by_stream(
        partner=identity["partner"],
        fetch_config_id=identity["fetchConfigId"],
        source_type=identity["sourceType"],
        stream_key=identity["streamKey"],
        mode=command.mode,
    )


def _apply_checkpoint(
    result: ExecuteStreamResult,
    checkpoint: Any,
) -> ExecuteStreamResult:
    if checkpoint is None:
        return result
    status = getattr(checkpoint.status, "value", checkpoint.status)
    return result.model_copy(
        update={
            "retryable": (
                checkpoint.retryable
                if checkpoint.retryable is not None
                else result.retryable
            ),
            "error_code": checkpoint.error_code or result.error_code,
            "next_retry_at": checkpoint.next_retry_at or result.next_retry_at,
            "checkpoint": {
                "status": status,
                "currentUnitKey": checkpoint.current_unit_key,
                "lastCompletedUnitKey": checkpoint.last_completed_unit_key,
                "cursorBefore": checkpoint.cursor_before,
                "cursorAfter": checkpoint.cursor_after,
            },
        }
    )


def _normalize_result(raw_result: dict[str, Any]) -> ExecuteStreamResult:
    runtime = raw_result.get("runtimeRun") or {}
    runtime_run_id = runtime.get("id") or raw_result.get("runtimeRunId")
    if not runtime_run_id:
        raise ValueError("stream execution did not return a runtime run id")

    return ExecuteStreamResult(
        runtimeRunId=str(runtime_run_id),
        outcome=_map_outcome(raw_result, runtime),
        retryable=raw_result.get("retryable") is True,
        errorCode=raw_result.get("errorCode"),
        nextRetryAt=raw_result.get("nextRetryAt"),
        message=raw_result.get("error") or raw_result.get("message"),
        checkpoint=raw_result.get("checkpoint"),
        counters={
            key: value
            for key, value in (raw_result.get("stats") or {}).items()
            if isinstance(value, int) and not isinstance(value, bool)
        },
    )


def _map_outcome(
    raw_result: dict[str, Any],
    runtime: dict[str, Any],
) -> ExecuteStreamOutcome:
    runtime_status = runtime.get("status")
    raw_outcome = raw_result.get("outcome")
    if runtime_status == "WAITING_REVIEW" or raw_outcome == "WAITING_REVIEW":
        return ExecuteStreamOutcome.WAITING_REVIEW
    if raw_outcome == "BLOCKED":
        return ExecuteStreamOutcome.BLOCKED
    if not raw_result.get("success"):
        return ExecuteStreamOutcome.FAILED
    if raw_outcome == "SAFE_DUPLICATE":
        return ExecuteStreamOutcome.SAFE_DUPLICATE
    if raw_result.get("streamAlreadyCompleted") or raw_outcome in {
        "FETCH_UNIT_REPLAY",
        "FILE_DUPLICATE",
    }:
        return ExecuteStreamOutcome.ALREADY_PROCESSED
    if raw_outcome == "NO_NEW_FILE":
        return ExecuteStreamOutcome.NO_DATA
    return ExecuteStreamOutcome.COMPLETED
