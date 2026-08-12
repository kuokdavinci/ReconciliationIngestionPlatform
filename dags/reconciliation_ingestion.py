"""Airflow control plane for sequential reconciliation ingestion streams."""

import asyncio
import json
import logging
import os
from datetime import timedelta
from typing import Any

import pendulum
from airflow.sdk import dag, get_current_context, task
from airflow.sdk.exceptions import AirflowFailException
from motor.motor_asyncio import AsyncIOMotorClient

from src.application.automation import ExecuteStreamCommand, OrchestrationContext, execute_stream
from src.application.automation.backfill_runner import execute_ordered_backfill
from src.application.automation.airflow_runtime import (
    resolve_reconciliation_date,
    resolve_schedule,
    select_stream_commands,
)
from src.application.automation.contracts import ExecuteStreamOutcome
from src.config.cache import ConfigCache
from src.config.loader import ConfigLoader
from src.config.settings import settings
from src.config.validator import ConfigValidator
from src.infrastructure.fetch_config.repository import FetchConfigRepository
from src.infrastructure.backfill.repository import BackfillRunRepository
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.services.runtime_runs import update_runtime_run
from src.domain.runtime.models import (
    PartnerRuntimeRunStatus,
    PartnerRuntimeTriggerType,
    RuntimeOrchestrationContext,
)
from src.services.runtime_runs import create_runtime_run

SUCCESS_OUTCOMES = {
    ExecuteStreamOutcome.COMPLETED,
    ExecuteStreamOutcome.NO_DATA,
    ExecuteStreamOutcome.ALREADY_PROCESSED,
    # Missing/changed mapping configuration is an operator gate, not a task
    # failure.  The application runtime remains WAITING_REVIEW and the
    # generated review packet is the source of truth for the next action.
    ExecuteStreamOutcome.WAITING_REVIEW,
}

logger = logging.getLogger("reconciliation.airflow")


def _stream_log_context(command: ExecuteStreamCommand, task_instance, dag_run) -> str:
    """Return stable identifiers that make one mapped stream searchable."""

    values = {
        "partner": command.partner,
        "runtimeRunId": command.runtime_run_id or "-",
        "fetchConfigId": command.fetch_config_id,
        "mappingVersion": command.mapping_version or "-",
        "reconciliationDate": command.reconciliation_date,
        "mode": command.mode,
        "backfillRunId": command.backfill_run_id or "-",
        "fromDate": command.from_date or "-",
        "toDate": command.to_date or "-",
        "dagRunId": dag_run.run_id,
        "taskId": task_instance.task_id,
        "mapIndex": task_instance.map_index,
        "tryNumber": task_instance.try_number,
    }
    return " ".join(f"{key}={value}" for key, value in values.items())

# Keep task-level retry policy operator-configurable. The UI's manual retry
# clears the task instance in the same DAG run; native Airflow retry remains a
# bounded fallback when the operator does nothing.
# Operator recovery is deliberately manual-only.  Airflow may still expose
# the task's failed state, but it must not start a second try on its own.
AIRFLOW_TASK_RETRIES = int(os.getenv("AIRFLOW_TASK_RETRIES", "0"))
AIRFLOW_TASK_RETRY_DELAY_SECONDS = int(
    os.getenv("AIRFLOW_TASK_RETRY_DELAY_SECONDS", "300")
)


async def _select_streams(
    conf: dict,
    reconciliation_date,
    dag_run_id: str,
) -> list[dict]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(settings.mongodb_url)
    try:
        repository = FetchConfigRepository(client[settings.db_name])
        return await select_stream_commands(
            conf=conf,
            reconciliation_date=reconciliation_date,
            dag_run_id=dag_run_id,
            repository=repository,
        )
    finally:
        client.close()


async def _execute_stream(payload: dict) -> dict:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(settings.mongodb_url)
    try:
        db = client[settings.db_name]
        config_loader = ConfigLoader(
            MappingConfigRepository(db),
            ConfigCache(),
            ConfigValidator(),
        )
        result = await execute_stream(
            ExecuteStreamCommand.model_validate(payload),
            db=db,
            config_loader=config_loader,
        )
        return result.model_dump(by_alias=True, mode="json")
    finally:
        client.close()


async def _execute_backfill(command: ExecuteStreamCommand, task_instance, dag_run) -> dict:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(settings.mongodb_url)
    try:
        db = client[settings.db_name]
        config_loader = ConfigLoader(
            MappingConfigRepository(db),
            ConfigCache(),
            ConfigValidator(),
        )
        backfill_repo = BackfillRunRepository(db)

        async def execute_day(day_command: ExecuteStreamCommand) -> dict:
            runtime_orchestration = None
            if day_command.orchestration is not None:
                runtime_orchestration = RuntimeOrchestrationContext.model_validate(
                    {
                        **day_command.orchestration.model_dump(by_alias=True),
                        "correlationId": day_command.correlation_id,
                    }
                )
            day_runtime = await create_runtime_run(
                db,
                partner=day_command.partner,
                date=day_command.reconciliation_date.isoformat(),
                trigger_type=PartnerRuntimeTriggerType.BACKFILL,
                triggered_by="airflow:backfill",
                status=PartnerRuntimeRunStatus.QUEUED,
                message="Backfill day queued for sequential execution.",
                orchestration=runtime_orchestration,
            )
            child_command = day_command.model_copy(
                update={"runtime_run_id": str(day_runtime.id)}
            )
            result = await execute_stream(
                child_command,
                db=db,
                config_loader=config_loader,
            )
            payload = result.model_dump(by_alias=True, mode="json")
            if payload.get("outcome") == ExecuteStreamOutcome.WAITING_REVIEW:
                packet = await db["review_packet"].find_one(
                    {
                        "partner": child_command.partner,
                        "status": "PENDING",
                    },
                    projection={"_id": 1},
                    sort=[("createdAt", -1)],
                )
                if packet is not None and command.backfill_run_id:
                    packet_id = str(packet["_id"])
                    await db["review_packet"].update_one(
                        {"_id": packet_id},
                        {"$set": {"backfillRunId": command.backfill_run_id}},
                    )
                    await backfill_repo.update_status(
                        command.backfill_run_id,
                        approvalContext={
                            "workflowType": "UPC",
                            "fileType": "SETTLEMENT",
                            "reviewPacketId": packet_id,
                            "reason": "Mapping approval is required before ordered backfill can continue.",
                        },
                    )
            return payload

        return await execute_ordered_backfill(
            command,
            backfill_repo=backfill_repo,
            execute_day=execute_day,
        )
    finally:
        client.close()


async def _mark_runtime_retrying(payload: dict, result: dict) -> None:
    """Keep the application runtime active while Airflow waits for its retry."""

    runtime_run_id = payload.get("runtimeRunId")
    if not runtime_run_id:
        return
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(settings.mongodb_url)
    try:
        db = client[settings.db_name]
        await update_runtime_run(
            db,
            str(runtime_run_id),
            status=PartnerRuntimeRunStatus.QUEUED,
            message="Transient source failure; Airflow retry is scheduled.",
            stats={
                "errorCode": result.get("errorCode") or "stream_execution_failed",
                "retryable": True,
                **(result.get("counters") or {}),
            },
            attempt_event={
                "eventId": f"{runtime_run_id}:retrying:{payload.get('orchestration', {}).get('tryNumber', 1)}",
                "status": "RETRYING",
                "timestamp": pendulum.now("UTC").to_iso8601_string(),
                "attempt": payload.get("orchestration", {}).get("tryNumber", 1),
                "errorCode": result.get("errorCode") or "stream_execution_failed",
                "message": "Transient source failure; Airflow retry is scheduled.",
            },
        )
    finally:
        client.close()


async def _mark_runtime_failed(
    payload: dict,
    *,
    error_code: str,
    message: str,
) -> None:
    """Persist a terminal Airflow-side failure for manually queued runtimes."""

    runtime_run_id = payload.get("runtimeRunId")
    if not runtime_run_id:
        return
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(settings.mongodb_url)
    try:
        db = client[settings.db_name]
        await update_runtime_run(
            db,
            str(runtime_run_id),
            status=PartnerRuntimeRunStatus.FAILED,
            message=message,
            stats={"errorCode": error_code, "retryable": False},
            finished_at=pendulum.now("UTC"),
            attempt_event={
                "eventId": f"{runtime_run_id}:failed:{pendulum.now('UTC').int_timestamp}",
                "status": "FAILED",
                "timestamp": pendulum.now("UTC").to_iso8601_string(),
                "attempt": payload.get("orchestration", {}).get("tryNumber", 1),
                "errorCode": error_code,
                "message": message,
            },
        )
    finally:
        client.close()


async def _mark_backfill_failed(payload: dict, message: str) -> None:
    """Close a parent backfill when Airflow fails before mapped tasks exist."""

    backfill_run_id = payload.get("backfillRunId")
    if not backfill_run_id:
        return
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(settings.mongodb_url)
    try:
        repository = BackfillRunRepository(client[settings.db_name])
        await repository.update_status(
            str(backfill_run_id),
            status="FAILED",
            approvalRequired=False,
            currentDate=payload.get("fromDate"),
        )
    finally:
        client.close()


@dag(
    dag_id="reconciliation_ingestion",
    schedule=resolve_schedule(os.getenv("AIRFLOW_GLOBAL_SCHEDULE", "0 0 * * *")),
    start_date=pendulum.datetime(2026, 1, 1, tz="Asia/Ho_Chi_Minh"),
    catchup=False,
    max_active_runs=1,
    tags=["reconciliation", "ingestion"],
)
def reconciliation_ingestion():
    @task(task_id="select_streams", retries=0)
    def select_streams_task() -> list[dict]:
        context = get_current_context()
        dag_run = context["dag_run"]
        conf = dict(dag_run.conf or {})
        try:
            return asyncio.run(
                _select_streams(
                    conf,
                    resolve_reconciliation_date(conf, context.get("data_interval_end")),
                    dag_run.run_id,
                )
            )
        except Exception as exc:
            message = f"Airflow stream selection failed: {str(exc)[:400]}"
            asyncio.run(_mark_backfill_failed(conf, message))
            asyncio.run(
                _mark_runtime_failed(
                    conf,
                    error_code="STREAM_SELECTION_FAILED",
                    message=message,
                )
            )
            raise

    @task(
        task_id="run_stream",
        pool="ingestion_streams",
        retries=AIRFLOW_TASK_RETRIES,
        retry_delay=timedelta(seconds=AIRFLOW_TASK_RETRY_DELAY_SECONDS),
        execution_timeout=timedelta(
            seconds=int(os.getenv("AIRFLOW_STREAM_TIMEOUT_SECONDS", "7200"))
        ),
        max_active_tis_per_dag=1,
    )
    def run_stream_task(payload: dict) -> dict:
        context = get_current_context()
        task_instance = context["ti"]
        dag_run = context["dag_run"]
        try:
            command = ExecuteStreamCommand.model_validate(payload)
        except Exception as exc:
            message = f"Airflow stream payload is invalid: {str(exc)[:400]}"
            asyncio.run(
                _mark_runtime_failed(
                    payload,
                    error_code="STREAM_PAYLOAD_INVALID",
                    message=message,
                )
            )
            raise
        command.orchestration = OrchestrationContext(
            dagId=task_instance.dag_id,
            dagRunId=dag_run.run_id,
            taskId=task_instance.task_id,
            mapIndex=task_instance.map_index,
            tryNumber=task_instance.try_number,
            logicalDate=dag_run.logical_date,
        )
        stream_context = _stream_log_context(command, task_instance, dag_run)
        logger.info(
            "stream_execution_started %s",
            stream_context,
        )
        try:
            if command.mode.value == "BACKFILL":
                result = asyncio.run(_execute_backfill(command, task_instance, dag_run))
            else:
                result = asyncio.run(
                    _execute_stream(command.model_dump(by_alias=True, mode="json", exclude_none=True))
                )
        except Exception as exc:
            logger.exception(
                "stream_execution_exception %s",
                stream_context,
            )
            if not isinstance(exc, ValueError) and task_instance.try_number <= AIRFLOW_TASK_RETRIES:
                asyncio.run(
                    _mark_runtime_retrying(
                        command.model_dump(by_alias=True, mode="json", exclude_none=True),
                        {
                            "errorCode": "STREAM_EXECUTION_EXCEPTION",
                            "retryable": True,
                            "counters": {},
                        },
                    )
                )
            else:
                asyncio.run(
                    _mark_runtime_failed(
                        command.model_dump(by_alias=True, mode="json", exclude_none=True),
                        error_code="STREAM_EXECUTION_EXCEPTION",
                        message=f"Airflow stream execution failed: {str(exc)[:400]}",
                    )
                )
            if isinstance(exc, ValueError):
                raise AirflowFailException(str(exc)) from exc
            raise
        logger.info(
            "stream_execution_result payload=%s %s",
            json.dumps(result, ensure_ascii=True, sort_keys=True, default=str),
            stream_context,
        )
        if result["outcome"] not in SUCCESS_OUTCOMES:
            error_code = result.get("errorCode") or "stream_execution_failed"
            message = result.get("message") or "No application error message returned."
            checkpoint = result.get("checkpoint") or {}
            counters = result.get("counters") or {}
            failure_message = (
                f"Stream execution stopped: {stream_context} "
                f"outcome={result.get('outcome')} errorCode={error_code} "
                f"message={message} checkpoint={checkpoint} counters={counters}"
            )
            # AirflowFailException is intentionally non-retryable.  Use a
            # normal exception for transient application failures so the task
            # retry policy can run (for example, a 504 on page 2).  Terminal
            # errors and blocked streams must still stop immediately.
            if (
                result.get("retryable") is True
                and task_instance.try_number <= AIRFLOW_TASK_RETRIES
            ):
                asyncio.run(
                    _mark_runtime_retrying(
                        command.model_dump(by_alias=True, mode="json", exclude_none=True),
                        result,
                    )
                )
                raise RuntimeError(failure_message)
            raise AirflowFailException(failure_message)
        logger.info(
            "stream_execution_succeeded %s outcome=%s checkpoint=%s counters=%s",
            stream_context,
            result.get("outcome"),
            result.get("checkpoint"),
            result.get("counters"),
        )
        return result

    run_stream_task.expand(payload=select_streams_task())


reconciliation_ingestion()
