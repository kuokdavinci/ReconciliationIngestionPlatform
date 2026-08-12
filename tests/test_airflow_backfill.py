from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.automation.contracts import ExecuteStreamCommand, ExecuteStreamOutcome
from src.domain.backfill.models import BackfillDayRecord, BackfillDayStatus, BackfillRun, BackfillRunStatus
from src.domain.ingestion.checkpoints import IngestionMode


def _run() -> BackfillRun:
    return BackfillRun(
        _id="backfill-1",
        partner="VNPAY",
        fetchConfigId="config-1",
        status=BackfillRunStatus.QUEUED,
        fromDate=date(2026, 8, 7),
        toDate=date(2026, 8, 11),
        currentDate=date(2026, 8, 7),
        totalDays=3,
        days=[
            BackfillDayRecord(businessDate=date(2026, 8, 7)),
            BackfillDayRecord(businessDate=date(2026, 8, 10)),
            BackfillDayRecord(businessDate=date(2026, 8, 11)),
        ],
    )


@pytest.mark.asyncio
async def test_ordered_backfill_stops_after_first_failed_day():
    from src.application.automation.backfill_runner import execute_ordered_backfill

    run = _run()
    repo = SimpleNamespace(
        find_by_id=AsyncMock(return_value=run),
        update_status=AsyncMock(),
        claim_day=AsyncMock(return_value=True),
        update_day=AsyncMock(),
    )
    seen: list[date] = []

    async def execute_day(command):
        seen.append(command.reconciliation_date)
        return SimpleNamespace(
            outcome=ExecuteStreamOutcome.FAILED,
            retryable=False,
            error_code="source_persist_error",
            message="failed",
            runtime_run_id="runtime-day-1",
            counters={},
        )

    result = await execute_ordered_backfill(
        ExecuteStreamCommand(
            fetchConfigId="config-1",
            partner="VNPAY",
            configVersion="fetch-v1",
            mode=IngestionMode.BACKFILL,
            runtimeRunId="backfill-1",
            backfillRunId="backfill-1",
            fromDate=date(2026, 8, 7),
            toDate=date(2026, 8, 11),
        ),
        backfill_repo=repo,
        execute_day=execute_day,
    )

    assert seen == [date(2026, 8, 7)]
    assert result["outcome"] == ExecuteStreamOutcome.FAILED
    repo.update_day.assert_awaited_once()
    assert repo.update_day.await_args.kwargs["status"] == BackfillDayStatus.FAILED.value


@pytest.mark.asyncio
async def test_ordered_backfill_completes_dates_in_ascending_order():
    from src.application.automation.backfill_runner import execute_ordered_backfill

    run = _run()
    repo = SimpleNamespace(
        find_by_id=AsyncMock(return_value=run),
        update_status=AsyncMock(),
        claim_day=AsyncMock(return_value=True),
        update_day=AsyncMock(),
    )
    seen: list[date] = []

    async def execute_day(command):
        seen.append(command.reconciliation_date)
        return SimpleNamespace(
            outcome=ExecuteStreamOutcome.COMPLETED,
            retryable=False,
            error_code=None,
            message="ok",
            runtime_run_id=f"runtime-{command.reconciliation_date}",
            counters={"reconciliationCount": 3},
        )

    result = await execute_ordered_backfill(
        ExecuteStreamCommand(
            fetchConfigId="config-1",
            partner="VNPAY",
            configVersion="fetch-v1",
            mode=IngestionMode.BACKFILL,
            runtimeRunId="backfill-1",
            backfillRunId="backfill-1",
            fromDate=date(2026, 8, 7),
            toDate=date(2026, 8, 11),
        ),
        backfill_repo=repo,
        execute_day=execute_day,
    )

    assert seen == [date(2026, 8, 7), date(2026, 8, 10), date(2026, 8, 11)]
    assert result["outcome"] == ExecuteStreamOutcome.COMPLETED
    assert result["completedDays"] == 3
