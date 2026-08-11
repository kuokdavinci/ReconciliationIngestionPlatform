import asyncio
from datetime import date

import httpx
import pytest

from src.application.automation import ExecuteStreamCommand
from src.application.automation.workflows import (
    WorkflowProvider,
    WorkflowSubmissionConflict,
    WorkflowSubmissionState,
)
from src.infrastructure.workflows.airflow import (
    AirflowWorkflowGateway,
    airflow_dag_run_id,
)
from src.infrastructure.workflows.local import LocalWorkflowGateway


def _command(runtime_run_id: str = "runtime-1") -> ExecuteStreamCommand:
    return ExecuteStreamCommand(
        fetchConfigId="config-1",
        partner="VIETTELPAY",
        configVersion="2026-08-09 01:02:03+00:00",
        reconciliationDate=date(2026, 8, 9),
        runtimeRunId=runtime_run_id,
        correlationId=f"runtime:{runtime_run_id}",
    )


def test_airflow_dag_run_id_is_deterministic_for_runtime() -> None:
    assert airflow_dag_run_id("runtime-1") == "manual__runtime-1"
    assert airflow_dag_run_id("runtime-1") == airflow_dag_run_id("runtime-1")
    assert airflow_dag_run_id("runtime-1") != airflow_dag_run_id("runtime-2")


@pytest.mark.asyncio
async def test_airflow_gateway_authenticates_and_submits_identifier_only_conf() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "jwt-token"})
        return httpx.Response(
            200,
            json={"dag_run_id": "manual__runtime-1", "state": "queued"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://airflow:8080",
    ) as client:
        submission = await AirflowWorkflowGateway(
            base_url="http://airflow:8080",
            dag_id="reconciliation_ingestion",
            username="service",
            password="secret",
            client=client,
        ).trigger(_command())

    assert submission.provider == WorkflowProvider.AIRFLOW
    assert submission.state == WorkflowSubmissionState.SUBMITTED
    assert submission.workflow_run_id == "manual__runtime-1"
    assert requests[0].url.path == "/auth/token"
    assert requests[0].content == b'{"username":"service","password":"secret"}'
    assert requests[1].headers["authorization"] == "Bearer jwt-token"
    payload = __import__("json").loads(requests[1].content)
    assert payload["logical_date"] is None
    assert payload["conf"] == {
        "schemaVersion": 1,
        "fetchConfigId": "config-1",
        "partner": "VIETTELPAY",
        "configVersion": "2026-08-09 01:02:03+00:00",
        "reconciliationDate": "2026-08-09",
        "mode": "SCHEDULED",
        "runtimeRunId": "runtime-1",
        "correlationId": "runtime:runtime-1",
    }
    assert "secret" not in str(payload)


@pytest.mark.asyncio
async def test_airflow_gateway_reads_task_instance_state() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "jwt-token"})
        return httpx.Response(200, json={"task_id": "run_stream", "state": "up_for_retry"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://airflow:8080",
    ) as client:
        state = await AirflowWorkflowGateway(
            base_url="http://airflow:8080",
            dag_id="reconciliation_ingestion",
            username="service",
            password="secret",
            client=client,
        ).task_state("manual__runtime-1", task_id="run_stream", map_index=2)

    assert state == "up_for_retry"
    assert requests[1].method == "GET"
    assert requests[1].url.path.endswith(
        "/dagRuns/manual__runtime-1/taskInstances/run_stream/2"
    )
    assert "map_index" not in requests[1].url.params
    assert requests[1].headers["authorization"] == "Bearer jwt-token"


@pytest.mark.asyncio
async def test_airflow_gateway_falls_back_to_failed_dag_run_when_task_is_cleared() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "jwt-token"})
        if request.url.path.endswith("/taskInstances/run_stream/0"):
            return httpx.Response(200, json={"task_id": "run_stream", "state": None})
        return httpx.Response(200, json={"dag_run_id": "manual__runtime-1", "state": "failed"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://airflow:8080",
    ) as client:
        state = await AirflowWorkflowGateway(
            base_url="http://airflow:8080",
            dag_id="reconciliation_ingestion",
            username="service",
            password="secret",
            client=client,
        ).task_state("manual__runtime-1", task_id="run_stream", map_index=0)

    assert state == "failed"
    assert requests[2].url.path.endswith("/dagRuns/manual__runtime-1")


@pytest.mark.asyncio
async def test_airflow_gateway_retries_task_in_existing_dag_run() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "jwt-token"})
        return httpx.Response(200, json={"task_instances": []})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://airflow:8080",
    ) as client:
        submission = await AirflowWorkflowGateway(
            base_url="http://airflow:8080",
            dag_id="reconciliation_ingestion",
            username="service",
            password="secret",
            client=client,
        ).retry_task("manual__runtime-1", task_id="run_stream", map_index=0)

    assert submission.state == WorkflowSubmissionState.RETRIED
    assert submission.workflow_run_id == "manual__runtime-1"
    assert requests[1].method == "POST"
    assert requests[1].url.path.endswith("/clearTaskInstances")
    assert requests[1].headers["authorization"] == "Bearer jwt-token"
    payload = __import__("json").loads(requests[1].content)
    assert payload["dry_run"] is False
    assert payload["dag_run_id"] == "manual__runtime-1"
    assert payload["task_ids"] == [["run_stream", 0]]
    assert payload["only_failed"] is False
    assert payload["prevent_running_task"] is True
    assert payload["reset_dag_runs"] is True


@pytest.mark.asyncio
async def test_airflow_gateway_treats_matching_conflict_as_idempotent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "jwt-token"})
        if request.method == "POST":
            return httpx.Response(409, json={"detail": "already exists"})
        return httpx.Response(
            200,
            json={
                "dag_run_id": "manual__runtime-1",
                "conf": {
                    "runtimeRunId": "runtime-1",
                    "correlationId": "runtime:runtime-1",
                },
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://airflow:8080",
    ) as client:
        submission = await AirflowWorkflowGateway(
            base_url="http://airflow:8080",
            dag_id="reconciliation_ingestion",
            username="service",
            password="secret",
            client=client,
        ).trigger(_command())

    assert submission.state == WorkflowSubmissionState.ALREADY_EXISTS


@pytest.mark.asyncio
async def test_airflow_gateway_verifies_run_after_submission_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "jwt-token"})
        if request.method == "POST":
            raise httpx.ReadTimeout("response lost", request=request)
        return httpx.Response(
            200,
            json={
                "dag_run_id": "manual__runtime-1",
                "conf": {
                    "runtimeRunId": "runtime-1",
                    "correlationId": "runtime:runtime-1",
                },
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://airflow:8080",
    ) as client:
        submission = await AirflowWorkflowGateway(
            base_url="http://airflow:8080",
            dag_id="reconciliation_ingestion",
            username="service",
            password="secret",
            client=client,
        ).trigger(_command())

    assert submission.state == WorkflowSubmissionState.ALREADY_EXISTS


@pytest.mark.asyncio
async def test_airflow_gateway_rejects_existing_run_with_different_correlation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "jwt-token"})
        if request.method == "POST":
            return httpx.Response(409, json={"detail": "already exists"})
        return httpx.Response(
            200,
            json={
                "dag_run_id": "manual__runtime-1",
                "conf": {
                    "runtimeRunId": "runtime-1",
                    "correlationId": "someone-else",
                },
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://airflow:8080",
    ) as client:
        gateway = AirflowWorkflowGateway(
            base_url="http://airflow:8080",
            dag_id="reconciliation_ingestion",
            username="service",
            password="secret",
            client=client,
        )
        with pytest.raises(WorkflowSubmissionConflict):
            await gateway.trigger(_command())


@pytest.mark.asyncio
async def test_local_gateway_tracks_background_execution() -> None:
    completed = asyncio.Event()
    tracked: list[asyncio.Task] = []

    async def runner(command: ExecuteStreamCommand) -> None:
        assert command.runtime_run_id == "runtime-1"
        completed.set()

    submission = await LocalWorkflowGateway(
        runner=runner,
        track_task=tracked.append,
    ).trigger(_command())
    await asyncio.wait_for(completed.wait(), timeout=1)

    assert submission.provider == WorkflowProvider.LOCAL
    assert submission.workflow_run_id == "local__runtime-1"
    assert len(tracked) == 1
    await tracked[0]
