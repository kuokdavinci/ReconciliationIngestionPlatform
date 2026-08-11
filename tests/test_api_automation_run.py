"""Tests for automation run-now endpoint."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _create_test_app():
    from fastapi import FastAPI
    from src.api.automation import router

    app = FastAPI()
    app.include_router(router)
    mock_db = MagicMock()
    def _create_mock_coll():
        coll = MagicMock()
        coll.find_one = AsyncMock(return_value=None)
        coll.find = MagicMock(return_value=[])
        coll.count_documents = AsyncMock(return_value=0)
        coll.insert_one = AsyncMock()
        coll.insert_many = AsyncMock(return_value=[])
        coll.update_one = AsyncMock()
        coll.delete_many = AsyncMock()
        return coll

    fetch_collection = _create_mock_coll()
    mapping_collection = _create_mock_coll()
    review_collection = _create_mock_coll()

    def _get_collection(name):
        if name == "fetch_config":
            return fetch_collection
        if name == "reconciliation_mapping_config":
            return mapping_collection
        if name == "review_packet":
            return review_collection
        return _create_mock_coll()

    mock_db.__getitem__ = MagicMock(side_effect=_get_collection)
    app.state.db = mock_db
    app.state.mongo_client = MagicMock()
    return app, fetch_collection


@pytest.mark.asyncio
async def test_run_automation_job_now():
    from src.api.automation import run_automation_job_now, settings
    from src.domain.runtime.models import PartnerRuntimeRun, PartnerRuntimeRunStatus, PartnerRuntimeTriggerType

    app, fetch_collection = _create_test_app()
    fetch_collection.find_one = AsyncMock(return_value={
        "_id": "123e4567-e89b-12d3-a456-426614174000",
        "partner": "ZALOPAY",
        "fetchMethod": "FILEDROP",
        "enabled": True,
        "schedule": "0 0 * * *",
        "localDownloadDir": "./downloads",
        "filedrop": {"directory": "sftp_data/zalopay_weird", "pattern": "*.csv"},
        "updatedAt": "2026-06-02T10:24:34.686000",
    })

    queued_run = PartnerRuntimeRun(
        partner="ZALOPAY",
        date="2026-08-05",
        triggerType=PartnerRuntimeTriggerType.SCHEDULER,
        triggeredBy="admin",
        status=PartnerRuntimeRunStatus.QUEUED,
        message="Automation run queued. Watch runtime state for live progress.",
    )

    def _discard_background_task(coro):
        coro.close()
        task = MagicMock()
        task.add_done_callback = MagicMock()
        return task

    with (
        patch("src.api.automation.create_runtime_run", new=AsyncMock(return_value=queued_run)),
        patch("src.api.automation.asyncio.create_task", side_effect=_discard_background_task),
        patch.object(settings, "automation_orchestrator", "apscheduler"),
    ):
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(db=app.state.db)),
            headers={"X-Actor": "admin"},
        )
        payload = await run_automation_job_now(request, "ZALOPAY")
        assert payload["ok"] is True
        assert payload["actor"] == "admin"
        assert payload["partner"] == "ZALOPAY"
        assert payload["runtimeRunId"] == str(queued_run.id)
        assert payload["run"]["_id"] == str(queued_run.id)


@pytest.mark.asyncio
async def test_run_now_does_not_queue_duplicate_while_airflow_is_up_for_retry():
    from fastapi import HTTPException

    from src.api.automation import run_automation_job_now
    from src.domain.runtime.models import (
        PartnerRuntimeRun,
        PartnerRuntimeRunStatus,
        PartnerRuntimeTriggerType,
        RuntimeOrchestrationContext,
    )

    app, fetch_collection = _create_test_app()
    fetch_collection.find_one = AsyncMock(return_value={
        "_id": "123e4567-e89b-12d3-a456-426614174000",
        "partner": "VIETTELPAY",
        "fetchMethod": "API",
        "enabled": True,
        "schedule": "0 0 * * *",
        "api": {"baseUrl": "http://viettelpay-mock:8001/settlement"},
        "updatedAt": "2026-08-09T01:02:03+00:00",
    })
    latest_run = PartnerRuntimeRun(
        partner="VIETTELPAY",
        date="2026-08-09",
        triggerType=PartnerRuntimeTriggerType.SCHEDULER,
        status=PartnerRuntimeRunStatus.FAILED,
        orchestration=RuntimeOrchestrationContext(
            dagId="reconciliation_ingestion",
            dagRunId="manual__runtime-1",
            taskId="run_stream",
            mapIndex=0,
        ),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db=app.state.db)),
        headers={"X-Actor": "ops-user"},
    )

    with (
        patch(
            "src.api.automation.PartnerRuntimeRunRepository.find_latest_by_partner",
            new=AsyncMock(return_value=latest_run),
        ),
        patch("src.api.automation._airflow_task_state", new=AsyncMock(return_value="up_for_retry")),
    ):
        with pytest.raises(HTTPException) as error:
            await run_automation_job_now(request, "VIETTELPAY")

    assert error.value.status_code == 409
    assert "already retrying" in str(error.value.detail)


@pytest.mark.asyncio
async def test_run_now_does_not_restart_a_stream_waiting_for_mapping_review():
    from fastapi import HTTPException

    from src.api.automation import run_automation_job_now

    app, fetch_collection = _create_test_app()
    fetch_collection.find_one = AsyncMock(return_value={
        "_id": "123e4567-e89b-12d3-a456-426614174000",
        "partner": "VIETTELPAY",
        "fetchMethod": "API",
        "enabled": True,
        "schedule": "0 0 * * *",
        "api": {
            "baseUrl": "http://mock-api:8090/settlement",
            "pagination": {"pageParam": "page", "nextCursorPath": "nextCursor"},
        },
        "updatedAt": "2026-08-09T01:02:03+00:00",
    })
    checkpoint = SimpleNamespace(
        status="DISCOVERED",
        error_code="configuration_approval_required",
        unit_timeline=[],
    )
    app.state.db["review_packet"].find_one = AsyncMock(
        return_value={"_id": "pending-review"}
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db=app.state.db)),
        headers={"X-Actor": "ops-user"},
    )

    with patch(
        "src.api.automation._find_recovery_checkpoint",
        new=AsyncMock(return_value=checkpoint),
    ):
        with pytest.raises(HTTPException) as error:
            await run_automation_job_now(request, "VIETTELPAY")

    assert error.value.status_code == 409
    assert "mapping review" in str(error.value.detail)


@pytest.mark.asyncio
async def test_run_now_allows_new_file_after_mapping_review_was_approved():
    from src.api.automation import run_automation_job_now, settings
    from src.domain.runtime.models import (
        PartnerRuntimeRun,
        PartnerRuntimeRunStatus,
        PartnerRuntimeTriggerType,
    )

    app, fetch_collection = _create_test_app()
    fetch_collection.find_one = AsyncMock(return_value={
        "_id": "123e4567-e89b-12d3-a456-426614174000",
        "partner": "MOMO",
        "fetchMethod": "FILEDROP",
        "enabled": True,
        "filedrop": {"directory": "mock_data", "pattern": "settlement_MOMO_*.xlsx"},
        "updatedAt": "2026-08-11T01:02:03+00:00",
    })
    checkpoint = SimpleNamespace(
        status="DISCOVERED",
        error_code="configuration_approval_required",
        unit_timeline=[],
    )
    app.state.db["review_packet"].find_one = AsyncMock(return_value=None)
    queued_run = PartnerRuntimeRun(
        partner="MOMO",
        date="2026-08-11",
        triggerType=PartnerRuntimeTriggerType.SCHEDULER,
        triggeredBy="ops-user",
        status=PartnerRuntimeRunStatus.QUEUED,
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db=app.state.db)),
        headers={"X-Actor": "ops-user"},
    )

    with (
        patch("src.api.automation._find_recovery_checkpoint", new=AsyncMock(return_value=checkpoint)),
        patch("src.api.automation.create_runtime_run", new=AsyncMock(return_value=queued_run)),
        patch.object(settings, "automation_orchestrator", "apscheduler"),
        patch("src.api.automation.asyncio.create_task") as create_task,
    ):
        create_task.side_effect = lambda coro: (coro.close(), MagicMock())[1]
        payload = await run_automation_job_now(request, "MOMO")

    assert payload["ok"] is True
    assert payload["partner"] == "MOMO"


@pytest.mark.asyncio
async def test_retry_without_checkpoint_starts_a_safe_fresh_fetch():
    from src.api.automation import retry_automation_job
    from src.application.automation.workflows import (
        WorkflowProvider,
        WorkflowSubmission,
        WorkflowSubmissionState,
    )
    from src.domain.runtime.models import (
        PartnerRuntimeRun,
        PartnerRuntimeRunStatus,
        PartnerRuntimeTriggerType,
    )

    app, fetch_collection = _create_test_app()
    fetch_collection.find_one = AsyncMock(return_value={
        "_id": "123e4567-e89b-12d3-a456-426614174000",
        "partner": "VIETTELPAY",
        "fetchMethod": "API",
        "enabled": True,
        "api": {"baseUrl": "http://viettelpay-mock:8001/viettelpay/settlement"},
        "updatedAt": "2026-08-09T01:02:03+00:00",
    })
    queued_run = PartnerRuntimeRun(
        partner="VIETTELPAY",
        date="2026-08-09",
        triggerType=PartnerRuntimeTriggerType.SCHEDULER,
        triggeredBy="ops-user",
        status=PartnerRuntimeRunStatus.QUEUED,
    )
    gateway = MagicMock()
    gateway.trigger = AsyncMock(return_value=WorkflowSubmission(
        provider=WorkflowProvider.AIRFLOW,
        workflowId="reconciliation_ingestion",
        workflowRunId=f"manual__{queued_run.id}",
        state=WorkflowSubmissionState.SUBMITTED,
    ))
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db=app.state.db, workflow_gateway=gateway)),
        headers={"X-Actor": "ops-user"},
    )

    with (
        patch("src.api.automation._find_recovery_checkpoint", new=AsyncMock(return_value=None)),
        patch("src.api.automation.create_runtime_run", new=AsyncMock(return_value=queued_run)),
        patch("src.api.automation.update_runtime_run", new=AsyncMock()),
    ):
        payload = await retry_automation_job(request, "VIETTELPAY")

    assert payload["ok"] is True
    assert payload["resumedFromUnitKey"] is None
    assert payload["runtimeRunId"] == str(queued_run.id)


@pytest.mark.asyncio
async def test_retry_manually_clears_up_for_retry_task_in_existing_airflow_run():
    from src.api.automation import retry_automation_job, settings
    from src.application.automation.workflows import (
        WorkflowProvider,
        WorkflowSubmission,
        WorkflowSubmissionState,
    )
    from src.domain.runtime.models import (
        PartnerRuntimeRun,
        PartnerRuntimeRunStatus,
        PartnerRuntimeTriggerType,
        RuntimeOrchestrationContext,
    )

    app, fetch_collection = _create_test_app()
    fetch_collection.find_one = AsyncMock(return_value={
        "_id": "123e4567-e89b-12d3-a456-426614174000",
        "partner": "VIETTELPAY",
        "fetchMethod": "API",
        "enabled": True,
        "schedule": "0 0 * * *",
        "api": {"baseUrl": "http://viettelpay-mock:8001/viettelpay/settlement"},
        "updatedAt": "2026-08-09T01:02:03+00:00",
    })
    latest_run = PartnerRuntimeRun(
        partner="VIETTELPAY",
        date="2026-08-09",
        triggerType=PartnerRuntimeTriggerType.SCHEDULER,
        triggeredBy="ops-user",
        status=PartnerRuntimeRunStatus.FAILED,
        orchestration=RuntimeOrchestrationContext(
            dagId="reconciliation_ingestion",
            dagRunId="manual__runtime-1",
            taskId="run_stream",
            mapIndex=0,
        ),
    )
    gateway = MagicMock()
    gateway.task_state = AsyncMock(return_value="up_for_retry")
    gateway.retry_task = AsyncMock(return_value=WorkflowSubmission(
        provider=WorkflowProvider.AIRFLOW,
        workflowId="reconciliation_ingestion",
        workflowRunId="manual__runtime-1",
        state=WorkflowSubmissionState.RETRIED,
    ))
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db=app.state.db, workflow_gateway=gateway)),
        headers={"X-Actor": "ops-user"},
    )

    with (
        patch.object(settings, "automation_orchestrator", "airflow"),
        patch(
            "src.api.automation.PartnerRuntimeRunRepository.find_latest_by_partner",
            new=AsyncMock(return_value=latest_run),
        ),
        patch("src.api.automation._find_recovery_checkpoint", new=AsyncMock(return_value=None)),
        patch("src.api.automation.update_runtime_run", new=AsyncMock()) as update_run,
        patch("src.api.automation.create_runtime_run", new=AsyncMock()) as create_run,
    ):
        payload = await retry_automation_job(request, "VIETTELPAY")

    assert payload["retried"] is True
    assert payload["runtimeRunId"] == str(latest_run.id)
    assert payload["workflow"]["state"] == "RETRIED"
    gateway.retry_task.assert_awaited_once_with(
        "manual__runtime-1",
        task_id="run_stream",
        map_index=0,
    )
    update_run.assert_awaited_once()
    create_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_refuses_new_run_when_existing_airflow_state_cannot_be_read():
    """An Airflow-backed runtime must fail closed instead of queueing a duplicate."""

    from fastapi import HTTPException

    from src.api.automation import retry_automation_job, settings
    from src.domain.runtime.models import (
        PartnerRuntimeRun,
        PartnerRuntimeRunStatus,
        PartnerRuntimeTriggerType,
        RuntimeOrchestrationContext,
    )

    app, fetch_collection = _create_test_app()
    fetch_collection.find_one = AsyncMock(return_value={
        "_id": "123e4567-e89b-12d3-a456-426614174000",
        "partner": "VIETTELPAY",
        "fetchMethod": "API",
        "enabled": True,
        "schedule": "0 0 * * *",
        "api": {"baseUrl": "http://viettelpay-mock:8001/viettelpay/settlement"},
        "updatedAt": "2026-08-09T01:02:03+00:00",
    })
    latest_run = PartnerRuntimeRun(
        partner="VIETTELPAY",
        date="2026-08-09",
        triggerType=PartnerRuntimeTriggerType.SCHEDULER,
        triggeredBy="ops-user",
        status=PartnerRuntimeRunStatus.FAILED,
        orchestration=RuntimeOrchestrationContext(
            dagId="reconciliation_ingestion",
            dagRunId="manual__runtime-1",
            taskId="run_stream",
            mapIndex=0,
        ),
    )
    gateway = MagicMock()
    gateway.task_state = AsyncMock(return_value=None)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db=app.state.db, workflow_gateway=gateway)),
        headers={"X-Actor": "ops-user"},
    )

    with (
        patch.object(settings, "automation_orchestrator", "airflow"),
        patch(
            "src.api.automation.PartnerRuntimeRunRepository.find_latest_by_partner",
            new=AsyncMock(return_value=latest_run),
        ),
        patch("src.api.automation._find_recovery_checkpoint", new=AsyncMock(return_value=None)),
        patch("src.api.automation._queue_scheduler_run", new=AsyncMock()) as queue_run,
    ):
        with pytest.raises(HTTPException) as error:
            await retry_automation_job(request, "VIETTELPAY")

    assert error.value.status_code == 409
    assert "no new Airflow DAG run was created" in str(error.value.detail)
    queue_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_automation_job_dispatches_through_injected_airflow_gateway():
    from src.api.automation import run_automation_job_now
    from src.application.automation.workflows import (
        WorkflowProvider,
        WorkflowSubmission,
        WorkflowSubmissionState,
    )
    from src.domain.runtime.models import (
        PartnerRuntimeRun,
        PartnerRuntimeRunStatus,
        PartnerRuntimeTriggerType,
    )

    app, fetch_collection = _create_test_app()
    config_id = "123e4567-e89b-12d3-a456-426614174000"
    fetch_collection.find_one = AsyncMock(
        return_value={
            "_id": config_id,
            "partner": "ZALOPAY",
            "fetchMethod": "FILEDROP",
            "enabled": True,
            "filedrop": {"directory": "sftp_data/zalopay", "pattern": "*.csv"},
            "updatedAt": "2026-08-09T01:02:03+00:00",
        }
    )
    queued_run = PartnerRuntimeRun(
        partner="ZALOPAY",
        date="2026-08-09",
        triggerType=PartnerRuntimeTriggerType.SCHEDULER,
        triggeredBy="admin",
        status=PartnerRuntimeRunStatus.QUEUED,
    )
    gateway = MagicMock()
    gateway.trigger = AsyncMock(
        return_value=WorkflowSubmission(
            provider=WorkflowProvider.AIRFLOW,
            workflowId="reconciliation_ingestion",
            workflowRunId=f"manual__{queued_run.id}",
            state=WorkflowSubmissionState.SUBMITTED,
        )
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(db=app.state.db, workflow_gateway=gateway)
        ),
        headers={"X-Actor": "admin"},
    )

    with (
        patch("src.api.automation.create_runtime_run", new=AsyncMock(return_value=queued_run)),
        patch("src.api.automation.update_runtime_run", new=AsyncMock()) as update_run,
    ):
        payload = await run_automation_job_now(request, "ZALOPAY")

    command = gateway.trigger.await_args.args[0]
    assert command.fetch_config_id == config_id
    assert command.runtime_run_id == str(queued_run.id)
    assert command.correlation_id == f"runtime:{queued_run.id}"
    assert payload["runtimeRunId"] == str(queued_run.id)
    assert payload["workflow"] == {
        "provider": "AIRFLOW",
        "workflowId": "reconciliation_ingestion",
        "workflowRunId": f"manual__{queued_run.id}",
        "state": "SUBMITTED",
    }
    assert payload["run"]["orchestration"]["dagRunId"] == f"manual__{queued_run.id}"
    assert update_run.await_args.kwargs["orchestration"]["correlationId"] == (
        f"runtime:{queued_run.id}"
    )


@pytest.mark.asyncio
async def test_run_automation_job_marks_runtime_failed_when_gateway_is_unavailable():
    from fastapi import HTTPException

    from src.api.automation import run_automation_job_now
    from src.application.automation.workflows import WorkflowUnavailable
    from src.domain.runtime.models import (
        PartnerRuntimeRun,
        PartnerRuntimeRunStatus,
        PartnerRuntimeTriggerType,
    )

    app, fetch_collection = _create_test_app()
    fetch_collection.find_one = AsyncMock(
        return_value={
            "_id": "123e4567-e89b-12d3-a456-426614174000",
            "partner": "ZALOPAY",
            "fetchMethod": "FILEDROP",
            "enabled": True,
            "filedrop": {"directory": "sftp_data/zalopay", "pattern": "*.csv"},
            "updatedAt": "2026-08-09T01:02:03+00:00",
        }
    )
    queued_run = PartnerRuntimeRun(
        partner="ZALOPAY",
        date="2026-08-09",
        triggerType=PartnerRuntimeTriggerType.SCHEDULER,
        status=PartnerRuntimeRunStatus.QUEUED,
    )
    gateway = MagicMock()
    gateway.trigger = AsyncMock(side_effect=WorkflowUnavailable("Airflow unavailable"))
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(db=app.state.db, workflow_gateway=gateway)
        ),
        headers={"X-Actor": "admin"},
    )

    with (
        patch("src.api.automation.create_runtime_run", new=AsyncMock(return_value=queued_run)),
        patch("src.api.automation.update_runtime_run", new=AsyncMock()) as update_run,
    ):
        with pytest.raises(HTTPException) as error:
            await run_automation_job_now(request, "ZALOPAY")

    assert error.value.status_code == 503
    assert update_run.await_args.kwargs["status"] == PartnerRuntimeRunStatus.FAILED
