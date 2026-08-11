from unittest.mock import AsyncMock

import pytest

from src.scheduler.source_unit_orchestrator import process_source_units
from src.services.retry_policy import RetryPolicy


def _unit(number: int, *, cursor_before=None, cursor_after=None):
    return {
        "sourceUnitKey": f"unit-{number}",
        "cursorBefore": cursor_before,
        "cursorAfter": cursor_after,
        "localPath": f"/tmp/page-{number}.json",
    }


@pytest.mark.asyncio
async def test_processes_units_in_order_and_stops_after_first_failure():
    checkpoint_repo = AsyncMock()
    checkpoint = AsyncMock()
    checkpoint.claim_id = "claim-1"
    checkpoint.last_completed_unit_key = None
    checkpoint_repo.claim_unit.return_value = (checkpoint, True)
    checkpoint_repo.mark_completed.return_value = True
    checkpoint_repo.advance.return_value = True
    checkpoint_repo.mark_failed.return_value = True

    ingest_unit = AsyncMock(
        side_effect=[
            {"success": True},
            {
                "success": False,
                "error": "partner rejected the page",
                "errorCode": "fetch_http_4xx",
                "retryable": False,
            },
            {"success": True},
        ]
    )

    result = await process_source_units(
        checkpoint_repo,
        stream_identity={
            "partner": "momo",
            "fetchConfigId": "config-1",
            "sourceType": "API",
            "streamKey": "momo-settlement",
        },
        units=[
            _unit(1, cursor_after="cursor-1"),
            _unit(2, cursor_before="cursor-1", cursor_after="cursor-2"),
            _unit(3, cursor_before="cursor-2"),
        ],
        ingest_unit=ingest_unit,
    )

    assert result == {
        "success": False,
        "processed": 1,
        "failed": 1,
        "stoppedAt": "unit-2",
        "error": "partner rejected the page",
    }
    assert ingest_unit.await_count == 2
    assert [call.args[0]["sourceUnitKey"] for call in ingest_unit.await_args_list] == [
        "unit-1",
        "unit-2",
    ]
    checkpoint_repo.mark_completed.assert_awaited_once_with(
        checkpoint,
        unit_key="unit-1",
        cursor_after="cursor-1",
        high_water_mark=None,
    )
    checkpoint_repo.advance.assert_awaited_once_with(checkpoint, unit_key="unit-1")
    checkpoint_repo.mark_failed.assert_awaited_once_with(
        checkpoint,
        unit_key="unit-2",
        error="partner rejected the page",
        error_code="fetch_http_4xx",
        retryable=False,
        next_retry_at=None,
        max_attempts=None,
        error_metadata={},
    )


@pytest.mark.asyncio
async def test_completed_unit_is_replay_safe_and_does_not_ingest_again():
    checkpoint_repo = AsyncMock()
    checkpoint = AsyncMock()
    checkpoint.last_completed_unit_key = "unit-1"
    checkpoint_repo.claim_unit.return_value = (checkpoint, False)
    ingest_unit = AsyncMock()

    result = await process_source_units(
        checkpoint_repo,
        stream_identity={
            "partner": "momo",
            "fetchConfigId": "config-1",
            "sourceType": "FILEDROP",
            "streamKey": "momo-settlement",
        },
        units=[_unit(1)],
        ingest_unit=ingest_unit,
    )

    assert result == {"success": True, "processed": 0, "failed": 0, "replayed": 1}
    ingest_unit.assert_not_awaited()


@pytest.mark.asyncio
async def test_operator_skip_advances_checkpoint_without_ingestion():
    checkpoint_repo = AsyncMock()
    checkpoint = AsyncMock()
    checkpoint.last_completed_unit_key = None
    checkpoint.current_unit_key = "unit-1"
    checkpoint.resolution_metadata = {"action": "SKIP", "operatorId": "ops-user"}
    checkpoint_repo.claim_unit.return_value = (checkpoint, True)
    checkpoint_repo.mark_completed.return_value = True
    checkpoint_repo.advance.return_value = True
    ingest_unit = AsyncMock()

    result = await process_source_units(
        checkpoint_repo,
        stream_identity={
            "partner": "momo",
            "fetchConfigId": "config-1",
            "sourceType": "API",
            "streamKey": "momo-settlement",
        },
        units=[_unit(1, cursor_after="cursor-1")],
        ingest_unit=ingest_unit,
    )

    assert result == {"success": True, "processed": 0, "failed": 0, "skipped": 1}
    ingest_unit.assert_not_awaited()
    checkpoint_repo.mark_completed.assert_awaited_once()
    checkpoint_repo.advance.assert_awaited_once_with(checkpoint, unit_key="unit-1")


@pytest.mark.asyncio
async def test_retry_policy_adds_backoff_and_bounds_attempts():
    checkpoint_repo = AsyncMock()
    checkpoint = AsyncMock()
    checkpoint.claim_id = "claim-1"
    checkpoint.last_completed_unit_key = None
    checkpoint.attempt_count = 1
    checkpoint_repo.claim_unit.return_value = (checkpoint, True)
    checkpoint_repo.mark_failed.return_value = True

    result = await process_source_units(
        checkpoint_repo,
        stream_identity={
            "partner": "momo",
            "fetchConfigId": "config-1",
            "sourceType": "API",
            "streamKey": "momo-settlement",
        },
        units=[_unit(1)],
        ingest_unit=AsyncMock(
            return_value={
                "success": False,
                "error": "gateway timeout",
                "errorCode": "fetch_timeout",
                "retryable": True,
            }
        ),
        retry_policy=RetryPolicy(initial_backoff_seconds=60),
    )

    assert result["success"] is False
    mark_failed_kwargs = checkpoint_repo.mark_failed.await_args.kwargs
    assert mark_failed_kwargs["max_attempts"] == 3
    assert mark_failed_kwargs["retryable"] is True
    assert mark_failed_kwargs["next_retry_at"] is not None


@pytest.mark.asyncio
async def test_worker_exception_releases_claim_for_airflow_retry():
    checkpoint_repo = AsyncMock()
    checkpoint = AsyncMock()
    checkpoint.last_completed_unit_key = None
    checkpoint.attempt_count = 1
    checkpoint_repo.claim_unit.return_value = (checkpoint, True)
    ingest_unit = AsyncMock(side_effect=RuntimeError("database connection lost"))

    with pytest.raises(RuntimeError, match="database connection lost"):
        await process_source_units(
            checkpoint_repo,
            stream_identity={
                "partner": "VIETTELPAY",
                "fetchConfigId": "config-1",
                "sourceType": "API",
                "streamKey": "viettelpay-settlement",
            },
            units=[_unit(1)],
            ingest_unit=ingest_unit,
            retry_policy=RetryPolicy(),
        )

    checkpoint_repo.mark_failed.assert_awaited_once_with(
        checkpoint,
        unit_key="unit-1",
        error="database connection lost",
        error_code="source_runtime_error",
        retryable=True,
        next_retry_at=None,
        max_attempts=3,
        error_metadata={"exceptionType": "RuntimeError"},
    )


@pytest.mark.asyncio
async def test_waiting_review_stops_without_marking_source_unit_failed():
    checkpoint_repo = AsyncMock()
    checkpoint = AsyncMock()
    checkpoint.last_completed_unit_key = None
    checkpoint_repo.claim_unit.return_value = (checkpoint, True)
    checkpoint_repo.release_for_review.return_value = True

    result = await process_source_units(
        checkpoint_repo,
        stream_identity={
            "partner": "momo",
            "fetchConfigId": "config-1",
            "sourceType": "FILEDROP",
            "streamKey": "momo-settlement",
        },
        units=[_unit(1)],
        ingest_unit=AsyncMock(
            return_value={
                "success": False,
                "outcome": "WAITING_REVIEW",
                "waitingForReview": True,
                "error": "A mapping draft is waiting for review.",
                "errorCode": "configuration_approval_required",
            }
        ),
    )

    assert result == {
        "success": True,
        "processed": 0,
        "failed": 0,
        "stoppedAt": "unit-1",
        "outcome": "WAITING_REVIEW",
        "waitingForReview": True,
        "error": "A mapping draft is waiting for review.",
    }
    checkpoint_repo.mark_failed.assert_not_awaited()
    checkpoint_repo.mark_completed.assert_not_awaited()
    checkpoint_repo.release_for_review.assert_awaited_once_with(
        checkpoint,
        unit_key="unit-1",
        reason="A mapping draft is waiting for review.",
    )


@pytest.mark.asyncio
async def test_all_file_duplicates_are_exposed_as_safe_duplicate_outcome():
    checkpoint_repo = AsyncMock()
    checkpoint = AsyncMock()
    checkpoint.last_completed_unit_key = None
    checkpoint_repo.claim_unit.return_value = (checkpoint, True)
    checkpoint_repo.mark_completed.return_value = True
    checkpoint_repo.advance.return_value = True

    result = await process_source_units(
        checkpoint_repo,
        stream_identity={
            "partner": "momo",
            "fetchConfigId": "config-1",
            "sourceType": "FILEDROP",
            "streamKey": "momo-settlement",
        },
        units=[_unit(1)],
        ingest_unit=AsyncMock(
            return_value={
                "success": True,
                "outcome": "FILE_DUPLICATE",
            }
        ),
    )

    assert result["outcome"] == "FILE_DUPLICATE"
    assert result["reconciliationSkipped"] is True


@pytest.mark.asyncio
async def test_completion_hook_runs_only_after_checkpoint_advance():
    checkpoint_repo = AsyncMock()
    checkpoint = AsyncMock()
    checkpoint.claim_id = "claim-1"
    checkpoint.last_completed_unit_key = None
    events = []
    checkpoint_repo.claim_unit.return_value = (checkpoint, True)
    checkpoint_repo.mark_completed.side_effect = lambda *_args, **_kwargs: events.append(
        "completed"
    ) or True
    checkpoint_repo.advance.side_effect = lambda *_args, **_kwargs: events.append(
        "advanced"
    ) or True

    async def on_completed(_unit):
        events.append("cleanup")

    result = await process_source_units(
        checkpoint_repo,
        stream_identity={
            "partner": "momo",
            "fetchConfigId": "config-1",
            "sourceType": "FILEDROP",
            "streamKey": "momo-settlement",
        },
        units=[_unit(1)],
        ingest_unit=AsyncMock(return_value={"success": True}),
        on_unit_completed=on_completed,
    )

    assert result["success"] is True
    assert events == ["completed", "advanced", "cleanup"]


@pytest.mark.asyncio
async def test_claims_follow_the_previous_checkpoint_boundary():
    checkpoint_repo = AsyncMock()
    checkpoint = AsyncMock()
    checkpoint.claim_id = "claim-1"
    checkpoint.last_completed_unit_key = None
    checkpoint_repo.claim_unit.return_value = (checkpoint, True)
    checkpoint_repo.mark_completed.return_value = True
    checkpoint_repo.advance.return_value = True

    await process_source_units(
        checkpoint_repo,
        stream_identity={
            "partner": "momo",
            "fetchConfigId": "config-1",
            "sourceType": "API",
            "streamKey": "momo-settlement",
        },
        units=[_unit(1), _unit(2, cursor_before="cursor-1")],
        ingest_unit=AsyncMock(return_value={"success": True}),
    )

    claims = checkpoint_repo.claim_unit.await_args_list
    assert claims[0].kwargs["expected_previous_unit_key"] is None
    assert claims[1].kwargs["expected_previous_unit_key"] == "unit-1"
