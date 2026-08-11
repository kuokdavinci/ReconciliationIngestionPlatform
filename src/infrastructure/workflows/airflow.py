"""Apache Airflow public REST API workflow adapter."""

from urllib.parse import quote

import httpx

from src.application.automation.contracts import ExecuteStreamCommand
from src.application.automation.workflows import (
    WorkflowProvider,
    WorkflowSubmission,
    WorkflowSubmissionConflict,
    WorkflowSubmissionState,
    WorkflowUnavailable,
)


def airflow_dag_run_id(runtime_run_id: str) -> str:
    if not runtime_run_id:
        raise ValueError("runtime_run_id is required for an Airflow submission")
    return f"manual__{runtime_run_id}"


class AirflowWorkflowGateway:
    def __init__(
        self,
        *,
        base_url: str,
        dag_id: str,
        username: str,
        password: str,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._dag_id = dag_id
        self._username = username
        self._password = password
        self._timeout = timeout_seconds
        self._client = client

    async def trigger(self, command: ExecuteStreamCommand) -> WorkflowSubmission:
        if self._client is not None:
            return await self._trigger(self._client, command)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await self._trigger(client, command)

    async def task_state(
        self,
        dag_run_id: str,
        *,
        task_id: str = "run_stream",
        map_index: int = 0,
    ) -> str | None:
        """Read the Airflow task state without creating another DAG run."""

        async def read(client: httpx.AsyncClient) -> str | None:
            token = await self._authenticate(client)
            headers = {"Authorization": f"Bearer {token}"}
            response = await client.get(
                f"{self._dag_runs_url}/{quote(dag_run_id, safe='')}/taskInstances/"
                f"{quote(task_id, safe='')}/{map_index}",
                headers=headers,
            )
            response.raise_for_status()
            value = response.json().get("state")
            if value is not None:
                return str(value)

            # A previous clear operation may have nulled the task instance
            # while leaving a terminal DagRun behind.  Expose the parent
            # state so the manual-retry endpoint can repair that transition.
            dag_run_response = await client.get(
                f"{self._dag_runs_url}/{quote(dag_run_id, safe='')}",
                headers=headers,
            )
            dag_run_response.raise_for_status()
            dag_run_state = dag_run_response.json().get("state")
            return str(dag_run_state) if dag_run_state is not None else None

        if self._client is not None:
            return await read(self._client)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await read(client)

    async def retry_task(
        self,
        dag_run_id: str,
        *,
        task_id: str = "run_stream",
        map_index: int = 0,
    ) -> WorkflowSubmission:
        """Clear one failed task in the existing DAG run for a fresh try."""

        async def clear(client: httpx.AsyncClient) -> WorkflowSubmission:
            try:
                token = await self._authenticate(client)
                response = await client.post(
                    f"{self._base_url}/api/v2/dags/{quote(self._dag_id, safe='')}/clearTaskInstances",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "dry_run": False,
                        # Target the mapped task instance that failed rather
                        # than clearing every map index in the DAG run.
                        "task_ids": [[task_id, map_index]],
                        "dag_run_id": dag_run_id,
                        # Manual retry may be requested while Airflow is
                        # UP_FOR_RETRY, not only after a terminal FAILED state.
                        "only_failed": False,
                        "only_running": False,
                        "prevent_running_task": True,
                        # Clearing a task in a terminal DAG run must put the
                        # DAG run back into QUEUED.  Without this, Airflow
                        # clears the task instance but leaves the parent run
                        # FAILED, so the scheduler never starts the manual
                        # retry.
                        "reset_dag_runs": True,
                        "include_upstream": False,
                        "include_downstream": False,
                        "include_future": False,
                        "include_past": False,
                    },
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise WorkflowUnavailable("Airflow task retry is unavailable") from exc
            return self._submission(dag_run_id, WorkflowSubmissionState.RETRIED)

        if self._client is not None:
            return await clear(self._client)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await clear(client)

    async def _trigger(
        self,
        client: httpx.AsyncClient,
        command: ExecuteStreamCommand,
    ) -> WorkflowSubmission:
        runtime_run_id = command.runtime_run_id
        if runtime_run_id is None:
            raise ValueError("runtime_run_id is required for an Airflow submission")
        dag_run_id = airflow_dag_run_id(runtime_run_id)
        try:
            token = await self._authenticate(client)
        except httpx.HTTPError as exc:
            raise WorkflowUnavailable("Airflow authentication is unavailable") from exc
        try:
            response = await client.post(
                self._dag_runs_url,
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "dag_run_id": dag_run_id,
                    "logical_date": None,
                    "conf": command.model_dump(
                        by_alias=True,
                        mode="json",
                        exclude={"orchestration"},
                        exclude_none=True,
                    ),
                },
            )
        except httpx.TimeoutException:
            return await self._resolve_existing(client, command, dag_run_id, token)
        except httpx.HTTPError as exc:
            raise WorkflowUnavailable("Airflow workflow submission is unavailable") from exc

        if response.status_code == 409:
            return await self._resolve_existing(client, command, dag_run_id, token)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise WorkflowUnavailable(
                f"Airflow rejected workflow submission with status {response.status_code}"
            ) from exc
        return self._submission(dag_run_id, WorkflowSubmissionState.SUBMITTED)

    async def _authenticate(self, client: httpx.AsyncClient) -> str:
        response = await client.post(
            f"{self._base_url}/auth/token",
            json={"username": self._username, "password": self._password},
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not isinstance(token, str) or not token:
            raise WorkflowUnavailable("Airflow authentication returned no access token")
        return token

    async def _resolve_existing(
        self,
        client: httpx.AsyncClient,
        command: ExecuteStreamCommand,
        dag_run_id: str,
        token: str,
    ) -> WorkflowSubmission:
        try:
            response = await client.get(
                f"{self._dag_runs_url}/{quote(dag_run_id, safe='')}",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise WorkflowUnavailable("Unable to verify an existing Airflow DAG run") from exc
        conf = response.json().get("conf") or {}
        runtime_matches = conf.get("runtimeRunId") == command.runtime_run_id
        correlation_matches = (
            command.correlation_id is None
            or conf.get("correlationId") == command.correlation_id
        )
        if not runtime_matches or not correlation_matches:
            raise WorkflowSubmissionConflict(
                "Airflow DAG run ID is already attached to another runtime"
            )
        return self._submission(dag_run_id, WorkflowSubmissionState.ALREADY_EXISTS)

    @property
    def _dag_runs_url(self) -> str:
        dag_id = quote(self._dag_id, safe="")
        return f"{self._base_url}/api/v2/dags/{dag_id}/dagRuns"

    def _submission(
        self,
        dag_run_id: str,
        state: WorkflowSubmissionState,
    ) -> WorkflowSubmission:
        return WorkflowSubmission(
            provider=WorkflowProvider.AIRFLOW,
            workflowId=self._dag_id,
            workflowRunId=dag_run_id,
            state=state,
        )
