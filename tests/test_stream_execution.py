from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application.automation import (
    ExecuteStreamCommand,
    ExecuteStreamOutcome,
    OrchestrationContext,
    execute_stream,
)
from src.domain.fetch_config.models import APIConfig, FetchConfig, FetchMethod


def _fetch_config() -> FetchConfig:
    return FetchConfig(
        partner="VIETTELPAY",
        fetchMethod=FetchMethod.API,
        api=APIConfig(baseUrl="https://partner.example/settlement"),
        updatedAt=datetime(2026, 8, 9, 1, 2, 3, tzinfo=UTC),
    )


def _checkpoint_repository(checkpoint=None):
    repository = MagicMock()
    repository.find_by_stream = AsyncMock(return_value=checkpoint)
    return repository


@pytest.mark.asyncio
async def test_execute_stream_loads_config_and_normalizes_no_data_result() -> None:
    config = _fetch_config()
    repository = MagicMock()
    repository.find_by_id = AsyncMock(return_value=config)
    runner = AsyncMock(
        return_value={
            "success": True,
            "outcome": "NO_NEW_FILE",
            "runtimeRun": {"id": "runtime-1", "status": "COMPLETED"},
            "stats": {"totalRows": 0, "successRows": 0},
        }
    )
    command = ExecuteStreamCommand(
        fetchConfigId=str(config.id),
        partner=config.partner,
        configVersion=str(config.updated_at),
        reconciliationDate=date(2026, 8, 9),
    )

    checkpoint_repository = _checkpoint_repository()
    with patch(
        "src.application.automation.service.IngestionCheckpointRepository",
        return_value=checkpoint_repository,
    ):
        result = await execute_stream(
            command,
            db=MagicMock(),
            config_loader=MagicMock(),
            fetch_config_repository=repository,
            runner=runner,
        )

    repository.find_by_id.assert_awaited_once_with(str(config.id))
    assert result.runtime_run_id == "runtime-1"
    assert result.outcome == ExecuteStreamOutcome.NO_DATA
    assert result.counters == {"totalRows": 0, "successRows": 0}
    assert runner.await_args is not None
    call = runner.await_args.kwargs
    assert call["config"] is config
    assert call["reconciliation_date"].isoformat() == "2026-08-09T00:00:00+07:00"
    assert call["raise_on_unexpected"] is True


@pytest.mark.asyncio
async def test_execute_stream_rejects_a_backfill_parent_without_a_day() -> None:
    config = _fetch_config()
    repository = MagicMock()
    repository.find_by_id = AsyncMock(return_value=config)
    runner = AsyncMock()

    with pytest.raises(ValueError, match="reconciliation_date is required"):
        await execute_stream(
            ExecuteStreamCommand(
                fetchConfigId=str(config.id),
                partner=config.partner,
                configVersion=str(config.updated_at),
                mode="BACKFILL",
                backfillRunId="backfill-1",
                fromDate=date(2026, 8, 9),
                toDate=date(2026, 8, 9),
            ),
            db=MagicMock(),
            config_loader=MagicMock(),
            fetch_config_repository=repository,
            runner=runner,
        )

    runner.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_stream_rejects_stale_config_version() -> None:
    config = _fetch_config()
    repository = MagicMock()
    repository.find_by_id = AsyncMock(return_value=config)
    runner = AsyncMock()
    command = ExecuteStreamCommand(
        fetchConfigId=str(config.id),
        partner=config.partner,
        configVersion="stale-version",
        reconciliationDate=date(2026, 8, 9),
        runtimeRunId="runtime-stale-config",
    )

    with patch("src.application.automation.service.update_runtime_run", new=AsyncMock()) as update:
        with pytest.raises(ValueError, match="config version changed"):
            await execute_stream(
                command,
                db=MagicMock(),
                config_loader=MagicMock(),
                fetch_config_repository=repository,
                runner=runner,
            )

    update.assert_awaited_once()
    assert update.await_args.kwargs["status"].value == "FAILED"
    assert update.await_args.kwargs["stats"]["errorCode"] == "CONFIG_VERSION_CHANGED"

    runner.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_stream_maps_waiting_review_without_retry() -> None:
    config = _fetch_config()
    repository = MagicMock()
    repository.find_by_id = AsyncMock(return_value=config)
    runner = AsyncMock(
        return_value={
            "success": False,
            "outcome": "WAITING_REVIEW",
            "errorCode": "configuration_approval_required",
            "retryable": False,
            "runtimeRun": {"id": "runtime-review", "status": "WAITING_REVIEW"},
            "stats": {},
        }
    )

    result = await execute_stream(
        ExecuteStreamCommand(
            fetchConfigId=str(config.id),
            partner=config.partner,
            configVersion=str(config.updated_at),
            reconciliationDate=date(2026, 8, 9),
        ),
        db=MagicMock(),
        config_loader=MagicMock(),
        fetch_config_repository=repository,
        checkpoint_repository=_checkpoint_repository(),
        runner=runner,
    )

    assert result.outcome == ExecuteStreamOutcome.WAITING_REVIEW
    assert result.retryable is False
    assert result.error_code == "configuration_approval_required"


@pytest.mark.asyncio
async def test_execute_stream_uses_checkpoint_as_failure_source_of_truth() -> None:
    config = _fetch_config()
    repository = MagicMock()
    repository.find_by_id = AsyncMock(return_value=config)
    checkpoint_repository = MagicMock()
    checkpoint_repository.find_by_stream = AsyncMock(
        return_value=SimpleNamespace(
            status="FAILED",
            current_unit_key="page:2",
            last_completed_unit_key="page:1",
            cursor_before="cursor-1",
            cursor_after=None,
            error_code="fetch_timeout",
            retryable=True,
            next_retry_at=datetime(2026, 8, 9, 2, 0, tzinfo=UTC),
        )
    )
    runner = AsyncMock(
        return_value={
            "success": False,
            "error": "Partner request failed",
            "runtimeRun": {"id": "runtime-failed", "status": "FAILED"},
            "stats": {},
        }
    )

    result = await execute_stream(
        ExecuteStreamCommand(
            fetchConfigId=str(config.id),
            partner=config.partner,
            configVersion=str(config.updated_at),
            reconciliationDate=date(2026, 8, 9),
        ),
        db=MagicMock(),
        config_loader=MagicMock(),
        fetch_config_repository=repository,
        checkpoint_repository=checkpoint_repository,
        runner=runner,
    )

    assert result.error_code == "fetch_timeout"
    assert result.retryable is True
    assert result.checkpoint == {
        "status": "FAILED",
        "currentUnitKey": "page:2",
        "lastCompletedUnitKey": "page:1",
        "cursorBefore": "cursor-1",
        "cursorAfter": None,
    }


@pytest.mark.asyncio
async def test_execute_stream_propagates_orchestration_context() -> None:
    config = _fetch_config()
    repository = MagicMock()
    repository.find_by_id = AsyncMock(return_value=config)
    runner = AsyncMock(
        return_value={
            "success": True,
            "runtimeRun": {"id": "runtime-airflow", "status": "COMPLETED"},
            "stats": {},
        }
    )
    orchestration = OrchestrationContext(
        dagId="reconciliation_ingestion",
        dagRunId="manual__runtime-airflow",
        taskId="run_stream",
        mapIndex=0,
        tryNumber=1,
    )

    await execute_stream(
        ExecuteStreamCommand(
            fetchConfigId=str(config.id),
            partner=config.partner,
            configVersion=str(config.updated_at),
            reconciliationDate=date(2026, 8, 9),
            runtimeRunId="runtime-airflow",
            correlationId="correlation-1",
            orchestration=orchestration,
        ),
        db=MagicMock(),
        config_loader=MagicMock(),
        fetch_config_repository=repository,
        checkpoint_repository=_checkpoint_repository(),
        runner=runner,
    )

    assert runner.await_args is not None
    assert runner.await_args.kwargs["orchestration"] == {
        "provider": "AIRFLOW",
        "dagId": "reconciliation_ingestion",
        "dagRunId": "manual__runtime-airflow",
        "taskId": "run_stream",
        "mapIndex": 0,
        "tryNumber": 1,
        "logicalDate": None,
        "correlationId": "correlation-1",
    }
