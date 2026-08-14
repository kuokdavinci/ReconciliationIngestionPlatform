from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_compose_uses_minimal_airflow_local_executor_topology() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]

    assert {
        "airflow-db-bootstrap",
        "airflow-init",
        "airflow-api-server",
        "airflow-scheduler",
        "airflow-dag-processor",
    } <= services.keys()
    assert "airflow-worker" not in services
    assert "redis" not in services
    assert services["airflow-api-server"]["command"] == "api-server"
    assert services["airflow-scheduler"]["command"] == "scheduler"
    assert services["airflow-dag-processor"]["command"] == "dag-processor"
    assert "scheduler" not in services
    environment = compose["x-airflow-common"]["environment"]
    assert environment["AIRFLOW__CORE__EXECUTOR"] == "LocalExecutor"
    assert environment["AIRFLOW__CORE__PARALLELISM"] == 2
    assert environment["AIRFLOW__CORE__DEFAULT_TIMEZONE"] == "${APP_BUSINESS_TIMEZONE:-Asia/Ho_Chi_Minh}"
    assert environment["AIRFLOW_GLOBAL_SCHEDULE"] == "${AIRFLOW_GLOBAL_SCHEDULE:-none}"
    assert environment["AIRFLOW_TASK_RETRIES"] == "${AIRFLOW_TASK_RETRIES:-0}"
    assert "AIRFLOW__API_AUTH__JWT_SECRET" in environment
    assert "AIRFLOW_TASK_RETRIES" in environment
    assert "AIRFLOW_TASK_RETRY_DELAY_SECONDS" in environment

    env_example = (ROOT / ".env.example").read_text()
    assert "AIRFLOW_JWT_SECRET=" in env_example
    assert "AIRFLOW_TASK_RETRIES=" in env_example
    assert "APP_AIRFLOW_REQUEST_TIMEOUT_SECONDS=" in env_example


def test_airflow_image_is_pinned_and_keeps_dags_in_image() -> None:
    dockerfile = (ROOT / "Dockerfile.airflow").read_text()

    assert "FROM apache/airflow:3.3.0-python3.11" in dockerfile
    assert "WORKDIR /opt/airflow/app" in dockerfile
    assert "requirements-airflow.txt /opt/airflow/requirements-airflow.txt" in dockerfile
    assert "apache-airflow==${AIRFLOW_VERSION}" not in dockerfile
    assert "COPY --chown=airflow:root dags /opt/airflow/dags" in dockerfile


def test_momo_rebuild_includes_airflow_services() -> None:
    makefile = (ROOT / "Makefile").read_text()

    rebuild_line = next(
        line for line in makefile.splitlines() if line.startswith("\tdocker compose up -d --build")
    )

    assert "api" in rebuild_line
    assert "airflow-api-server" in rebuild_line
    assert "airflow-scheduler" in rebuild_line
    assert "airflow-dag-processor" in rebuild_line
    assert " scheduler" not in rebuild_line


def test_airflow_dag_uses_public_sdk_and_global_schedule() -> None:
    dag_source = (ROOT / "dags/reconciliation_ingestion.py").read_text()

    assert "from airflow.sdk import dag, get_current_context, task" in dag_source
    assert 'schedule=resolve_schedule(os.getenv("AIRFLOW_GLOBAL_SCHEDULE", "0 0 * * *"))' in dag_source
    assert "catchup=False" in dag_source
    assert "max_active_runs=1" in dag_source
    assert 'pool="ingestion_streams"' in dag_source
    assert ".expand(" in dag_source
    assert "ExecuteStreamOutcome.WAITING_REVIEW" in dag_source
    assert "stream_execution_result payload=" in dag_source
    assert "fetchConfigId" in dag_source
    runner_source = (ROOT / "src/application/automation/stream_runner.py").read_text()
    assert "source_unit_fetched" in runner_source
    assert "sourceUnitKey=" in runner_source
    assert "checkpoint={checkpoint}" in dag_source
    assert "counters={counters}" in dag_source
    assert "stream_execution_exception" in dag_source
    assert 'result.get("retryable") is True' in dag_source
    assert "_mark_runtime_failed" in dag_source
    assert 'error_code="STREAM_SELECTION_FAILED"' in dag_source
    assert 'error_code="STREAM_PAYLOAD_INVALID"' in dag_source
    assert "if isinstance(exc, ValueError):" in dag_source
    assert "raise AirflowFailException(str(exc)) from exc" in dag_source
    assert "raise RuntimeError(failure_message)" in dag_source
    assert "_mark_runtime_retrying" in dag_source
    assert 'task_instance.try_number <= AIRFLOW_TASK_RETRIES' in dag_source
    assert 'os.getenv("AIRFLOW_TASK_RETRIES", "0")' in dag_source
    assert 'os.getenv("AIRFLOW_TASK_RETRY_DELAY_SECONDS", "300")' in dag_source


def test_airflow_runner_does_not_require_legacy_scheduler_dependency() -> None:
    script = """
import builtins

real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name.startswith("apscheduler"):
        raise ModuleNotFoundError("apscheduler intentionally unavailable")
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
from src.application.automation import run_source_stream
assert callable(run_source_stream)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
