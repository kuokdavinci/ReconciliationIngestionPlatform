from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.automation.job_commands import AutomationJobCommandService
from src.application.automation.job_queries import AutomationJobQueryService
from src.application.automation.job_contracts import (
    AutomationConflictError,
    ResolveAutomationRecoveryCommand,
    RetryAutomationJobCommand,
    RunAutomationJobCommand,
)
from src.application.automation.workflows import (
    WorkflowProvider,
    WorkflowSubmission,
    WorkflowSubmissionState,
)


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        enabled=True,
        partner="VNPAY",
        id="config-1",
        updated_at="2026-08-13T00:00:00+00:00",
        fetch_method=SimpleNamespace(value="API"),
    )


def _checkpoint(status: str, **changes) -> SimpleNamespace:
    values = {
        "status": status,
        "current_unit_key": "page:2",
        "started_at": None,
        "retryable": True,
        "error_code": None,
        "unit_timeline": [],
        "resolution_metadata": {},
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _service(
    *,
    checkpoint=None,
    latest_run=None,
    task_state=None,
    queue_run=None,
    gateway=None,
    checkpoint_repo=None,
) -> AutomationJobCommandService:
    return AutomationJobCommandService(
        fetch_repo=SimpleNamespace(find_by_partner=AsyncMock(return_value=_config())),
        backfill_repo=SimpleNamespace(
            find_latest_active_by_partner=AsyncMock(return_value=None)
        ),
        runtime_repo=SimpleNamespace(
            find_latest_by_partner=AsyncMock(return_value=latest_run),
            update_fields=AsyncMock(),
        ),
        checkpoint_repo=checkpoint_repo or SimpleNamespace(
            prepare_manual_retry=AsyncMock(return_value=True),
            resolve_blocked=AsyncMock(return_value=True),
        ),
        workflow_gateway=gateway or MagicMock(),
        runtime_service=SimpleNamespace(
            serialize_partner_runtime_run=lambda run: {
                "status": getattr(run.status, "value", run.status),
                "orchestration": getattr(run, "orchestration", None),
            }
        ),
        checkpoint_finder=AsyncMock(return_value=checkpoint),
        task_state_resolver=AsyncMock(return_value=task_state),
        queue_run=queue_run,
    )


@pytest.mark.asyncio
async def test_run_now_rejects_partner_with_active_backfill() -> None:
    active_backfill = SimpleNamespace(
        status="WAITING_CONFIG",
        current_date=SimpleNamespace(isoformat=lambda: "2026-08-10"),
    )
    service = _service()
    service.backfill_repo.find_latest_active_by_partner.return_value = active_backfill

    with pytest.raises(AutomationConflictError, match="Backfill is WAITING_CONFIG"):
        await service.run_now(RunAutomationJobCommand(partner="VNPAY", actor="operator"))


@pytest.mark.asyncio
async def test_run_now_rejects_active_runtime() -> None:
    service = _service(latest_run=SimpleNamespace(status="FETCHING"))

    with pytest.raises(AutomationConflictError, match="already active"):
        await service.run_now(RunAutomationJobCommand(partner="VNPAY", actor="operator"))


@pytest.mark.asyncio
async def test_run_now_rejects_airflow_native_retry() -> None:
    service = _service(
        latest_run=SimpleNamespace(status="FAILED"),
        task_state="up_for_retry",
    )

    with pytest.raises(AutomationConflictError, match="already retrying"):
        await service.run_now(RunAutomationJobCommand(partner="VNPAY", actor="operator"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("checkpoint", "message"),
    [
        (_checkpoint("BLOCKED"), "BLOCKED"),
        (
            _checkpoint(
                "DISCOVERED",
                error_code="configuration_approval_required",
            ),
            "mapping review",
        ),
        (_checkpoint("FAILED", retryable=False), "terminal"),
    ],
)
async def test_run_now_rejects_blocked_review_and_terminal_checkpoint(
    checkpoint, message
) -> None:
    service = _service(checkpoint=checkpoint)

    with pytest.raises(AutomationConflictError, match=message):
        await service.run_now(RunAutomationJobCommand(partner="VNPAY", actor="operator"))


@pytest.mark.asyncio
async def test_retry_retries_existing_airflow_task_in_place() -> None:
    latest_run = SimpleNamespace(
        id="runtime-1",
        partner="VNPAY",
        status="FAILED",
        orchestration={
            "dagRunId": "dag-run-1",
            "taskId": "run_stream",
            "mapIndex": 0,
        },
        attempt_history=[],
        message=None,
        finished_at="finished",
    )
    gateway = MagicMock()
    gateway.retry_task = AsyncMock(
        return_value=WorkflowSubmission(
            provider=WorkflowProvider.AIRFLOW,
            workflowId="stream_fetch",
            workflowRunId="dag-run-1",
            state=WorkflowSubmissionState.RETRIED,
        )
    )
    service = _service(
        latest_run=latest_run,
        task_state="failed",
        gateway=gateway,
    )

    result = await service.retry(
        RetryAutomationJobCommand(partner="VNPAY", actor="operator")
    )

    assert result["retried"] is True
    gateway.retry_task.assert_awaited_once()
    service.runtime_repo.update_fields.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_queues_new_run_when_fetch_failed_before_checkpoint() -> None:
    queue_run = AsyncMock(
        return_value={
            "ok": True,
            "queued": True,
            "message": "Retry queued after a fetch failure before checkpoint creation.",
        }
    )
    service = _service(queue_run=queue_run)

    result = await service.retry(
        RetryAutomationJobCommand(partner="VNPAY", actor="operator")
    )

    assert result["queued"] is True
    queue_run.assert_awaited_once()
    assert queue_run.await_args.args[1] == "operator"


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["RETRY", "SKIP"])
async def test_resolve_applies_blocked_checkpoint_action(action: str) -> None:
    checkpoint_repo = SimpleNamespace(resolve_blocked=AsyncMock(return_value=True))
    service = _service(
        checkpoint=_checkpoint("BLOCKED"),
        checkpoint_repo=checkpoint_repo,
    )

    result = await service.resolve(
        ResolveAutomationRecoveryCommand(
            partner="VNPAY",
            actor="operator",
            action=action,
            reason="Operator reviewed the source unit.",
        )
    )

    assert result["ok"] is True
    assert result["action"] == action
    assert result["partner"] == "VNPAY"
    assert result["unitKey"] == "page:2"
    checkpoint_repo.resolve_blocked.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_jobs_builds_operator_projection_from_injected_repositories() -> None:
    config = _config()
    config.updated_at = datetime(2026, 8, 13, tzinfo=timezone.utc)
    config.schedule = "0 2 * * *"
    config.local_download_dir = None
    config.get_method_config = lambda: None
    db = MagicMock()
    db["reconciliation_file"].find_one = AsyncMock(return_value=None)
    service = AutomationJobQueryService(
        db=db,
        fetch_repo=SimpleNamespace(find_enabled=AsyncMock(return_value=[config])),
        packet_repo=SimpleNamespace(find_many=AsyncMock(return_value=[])),
        runtime_run_repo=SimpleNamespace(
            find_latest_by_partner=AsyncMock(return_value=None),
            find_recent_by_partner=AsyncMock(return_value=[]),
        ),
        checkpoint_repo=SimpleNamespace(find_by_streams=AsyncMock(return_value=[])),
        backfill_repo=SimpleNamespace(
            find_latest_active_by_partner=AsyncMock(return_value=None)
        ),
        task_state_resolver=AsyncMock(return_value=None),
    )

    jobs = await service.list_jobs()

    assert [job["partner"] for job in jobs] == ["VNPAY"]
    assert jobs[0]["status"] == "HEALTHY"
