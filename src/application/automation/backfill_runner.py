"""Ordered application-level execution for one Airflow backfill run."""

from collections.abc import Awaitable, Callable
from typing import Any

from src.application.automation.contracts import ExecuteStreamCommand, ExecuteStreamOutcome
from src.domain.backfill.models import BackfillDayStatus, BackfillRunStatus

SUCCESS_OUTCOMES = {
    ExecuteStreamOutcome.COMPLETED,
    ExecuteStreamOutcome.NO_DATA,
    ExecuteStreamOutcome.ALREADY_PROCESSED,
    ExecuteStreamOutcome.SAFE_DUPLICATE,
}


def _result_value(result: Any, attribute: str, key: str, default: Any = None) -> Any:
    if isinstance(result, dict):
        return result.get(key, default)
    return getattr(result, attribute, default)


async def execute_ordered_backfill(
    command: ExecuteStreamCommand,
    *,
    backfill_repo: Any,
    execute_day: Callable[[ExecuteStreamCommand], Awaitable[Any]],
) -> dict[str, Any]:
    """Execute only the next backfill day until a boundary fails or waits for review."""

    if command.backfill_run_id is None:
        raise ValueError("backfillRunId is required for ordered backfill execution")
    run = await backfill_repo.find_by_id(command.backfill_run_id)
    if run is None:
        raise ValueError(f"Backfill run '{command.backfill_run_id}' was not found")

    completed_days = int(run.completed_days)
    await backfill_repo.update_status(
        command.backfill_run_id,
        status=BackfillRunStatus.RUNNING.value,
    )

    for day in run.days:
        day_status = getattr(day.status, "value", day.status)
        if day_status == BackfillDayStatus.COMPLETED.value:
            continue

        business_date = day.business_date
        claimed = await backfill_repo.claim_day(
            command.backfill_run_id,
            business_date.isoformat(),
        )
        if not claimed:
            return {
                "success": False,
                "outcome": ExecuteStreamOutcome.FAILED,
                "errorCode": "backfill_day_claim_conflict",
                "message": f"Backfill day {business_date} could not be claimed.",
                "completedDays": completed_days,
            }

        day_command = command.model_copy(update={"reconciliation_date": business_date})
        result = await execute_day(day_command)
        outcome = ExecuteStreamOutcome(_result_value(result, "outcome", "outcome"))
        runtime_run_id = _result_value(result, "runtime_run_id", "runtimeRunId")
        message = _result_value(result, "message", "message")
        if outcome in SUCCESS_OUTCOMES:
            completed_days += 1
            await backfill_repo.update_day(
                command.backfill_run_id,
                business_date.isoformat(),
                status=BackfillDayStatus.COMPLETED.value,
                runtimeRunId=runtime_run_id,
                message=message or outcome.value,
            )
            next_date = next(
                (
                    candidate.business_date
                    for candidate in run.days
                    if candidate.business_date > business_date
                    and getattr(candidate.status, "value", candidate.status)
                    != BackfillDayStatus.COMPLETED.value
                ),
                None,
            )
            await backfill_repo.update_status(
                command.backfill_run_id,
                completedDays=completed_days,
                currentDate=next_date,
            )
            continue

        if outcome == ExecuteStreamOutcome.WAITING_REVIEW:
            await backfill_repo.update_day(
                command.backfill_run_id,
                business_date.isoformat(),
                status=BackfillDayStatus.WAITING_CONFIG.value,
                runtimeRunId=runtime_run_id,
                message=message or "Mapping approval is required.",
            )
            await backfill_repo.update_status(
                command.backfill_run_id,
                status=BackfillRunStatus.WAITING_CONFIG.value,
                approvalRequired=True,
                currentDate=business_date,
            )
            return {
                "success": True,
                "outcome": ExecuteStreamOutcome.WAITING_REVIEW,
                "message": message or "Mapping approval is required.",
                "completedDays": completed_days,
            }

        error_code = _result_value(result, "error_code", "errorCode")
        await backfill_repo.update_day(
            command.backfill_run_id,
            business_date.isoformat(),
            status=BackfillDayStatus.FAILED.value,
            runtimeRunId=runtime_run_id,
            message=message or error_code or outcome.value,
        )
        await backfill_repo.update_status(
            command.backfill_run_id,
            status=BackfillRunStatus.FAILED.value,
            completedDays=completed_days,
            currentDate=business_date,
        )
        return {
            "success": False,
            "outcome": outcome,
            "errorCode": error_code,
            "message": message or outcome.value,
            "completedDays": completed_days,
        }

    await backfill_repo.update_status(
        command.backfill_run_id,
        status=BackfillRunStatus.COMPLETED.value,
        completedDays=completed_days,
        currentDate=None,
    )
    return {
        "success": True,
        "outcome": ExecuteStreamOutcome.COMPLETED,
        "completedDays": completed_days,
        "totalDays": len(run.days),
    }
