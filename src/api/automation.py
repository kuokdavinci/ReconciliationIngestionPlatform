"""Automation visibility endpoints for scheduler/admin views."""

import asyncio
import inspect
import logging
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.actor import require_actor
from src.application.automation import ExecuteStreamCommand, execute_stream
from src.application.automation.workflows import (
    WorkflowGateway,
    WorkflowProvider,
    WorkflowSubmission,
    WorkflowSubmissionConflict,
    WorkflowUnavailable,
)
from src.application.ingestion.recovery_view import build_recovery_view
from src.config.settings import settings
from src.domain.fetch_config.models import FetchMethod
from src.domain.ingestion.checkpoints import IngestionMode
from src.infrastructure.backfill.repository import BackfillRunRepository
from src.infrastructure.fetch_config.repository import FetchConfigRepository
from src.infrastructure.ingestion.checkpoint_repository import IngestionCheckpointRepository
from src.domain.runtime.models import (
    PartnerRuntimeRunStatus,
    PartnerRuntimeTriggerType,
    RuntimeOrchestrationContext,
)
from src.infrastructure.runtime.repository import PartnerRuntimeRunRepository
from src.infrastructure.review.repository import ReviewPacketRepository
from src.scheduler.jobs import _source_stream_key
from src.services.backfill_runs import (
    BackfillRunError,
    BackfillRunService,
    serialize_backfill_run,
)
from src.services.runtime_runs import (
    create_runtime_run,
    serialize_partner_runtime_run,
    update_runtime_run,
)
from src.services.retry_policy import RetryPolicy
from src.services.audit import record_audit_event
from src.services.review_packet_actions import build_config_loader_from_db
from src.api.background_tasks import track_background_task
from src.infrastructure.workflows.airflow import AirflowWorkflowGateway
from src.infrastructure.workflows.local import LocalWorkflowGateway

router = APIRouter(prefix="/api/v1/automation")
logger = logging.getLogger("reconciliation.automation")
_CLAIM_TIMEOUT_SECONDS = 900
_ACTIVE_RUNTIME_STATUSES = {
    PartnerRuntimeRunStatus.QUEUED.value,
    PartnerRuntimeRunStatus.FETCHING.value,
    PartnerRuntimeRunStatus.INGESTING.value,
    PartnerRuntimeRunStatus.WAITING_REVIEW.value,
    PartnerRuntimeRunStatus.WAITING_RECONCILE.value,
    PartnerRuntimeRunStatus.RECONCILING.value,
}
_AIRFLOW_RETRYING_TASK_STATES = {
    "up_for_retry",
}
_AIRFLOW_MANUAL_RETRY_STATES = {"failed", "upstream_failed", "up_for_retry"}


class _LazyWorkflowGateway:
    """Resolve the workflow adapter only when a run is actually submitted."""

    def __init__(self, factory):
        self._factory = factory
        self._gateway: WorkflowGateway | None = None

    async def trigger(self, command: ExecuteStreamCommand) -> WorkflowSubmission:
        if self._gateway is None:
            self._gateway = self._factory()
        return await self._gateway.trigger(command)


def _stream_key_for_config(config) -> str | None:
    try:
        return _source_stream_key(config)
    except (AttributeError, ValueError):
        return None


async def _find_recovery_checkpoint(checkpoint_repo, config):
    stream_key = _stream_key_for_config(config)
    if stream_key is not None:
        return await checkpoint_repo.find_by_stream(
            partner=config.partner,
            fetch_config_id=str(config.id),
            source_type=config.fetch_method.value,
            stream_key=stream_key,
            mode=IngestionMode.SCHEDULED,
        )
    checkpoints = await checkpoint_repo.find_by_streams([
        {
            "partner": config.partner,
            "fetchConfigId": str(config.id),
            "sourceType": config.fetch_method.value,
            "streamKey": None,
            "mode": IngestionMode.SCHEDULED,
        }
    ])
    return max(checkpoints, key=lambda checkpoint: checkpoint.updated_at, default=None)


def _has_live_claim(checkpoint) -> bool:
    if checkpoint.status != "PROCESSING":
        return False
    if checkpoint.started_at is None:
        return True
    started_at = checkpoint.started_at
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return started_at > datetime.now(timezone.utc) - timedelta(seconds=_CLAIM_TIMEOUT_SECONDS)


def _merge_runtime_attempt_history(
    recent_runs: list,
    latest_run_data: dict | None,
) -> list[dict]:
    """Keep recovery history when a manual retry creates a new runtime run."""

    merged: list[dict] = []
    seen: set[str] = set()
    for run in reversed(recent_runs):
        for event in getattr(run, "attempt_history", None) or []:
            event_id = str(event.get("eventId") or "") if isinstance(event, dict) else ""
            if not event_id or event_id in seen:
                continue
            seen.add(event_id)
            merged.append(dict(event))
    for event in (latest_run_data or {}).get("attemptHistory") or []:
        event_id = str(event.get("eventId") or "") if isinstance(event, dict) else ""
        if not event_id or event_id in seen:
            continue
        seen.add(event_id)
        merged.append(dict(event))
    return merged


def _checkpoint_waiting_for_mapping_review(checkpoint) -> bool:
    """Identify a released checkpoint that must wait for the review packet.

    A normal completed page also leaves a checkpoint in ``DISCOVERED`` while a
    stream is being advanced, so the status alone is not enough to block
    ``Run now``.  The persisted error code/timeline is the durable marker for
    the mapping gate.
    """

    if checkpoint.status != "DISCOVERED":
        return False
    if checkpoint.error_code == "configuration_approval_required":
        return True
    return any(
        getattr(unit, "status", None) == "WAITING_REVIEW"
        or getattr(getattr(unit, "status", None), "value", None) == "WAITING_REVIEW"
        for unit in (checkpoint.unit_timeline or [])
    )


def _get_db(request: Request):
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available.")
    return db


def _has_pending_file(
    *,
    fetch_method: FetchMethod,
    latest_file: dict | None,
    latest_run,
    is_duplicate_outcome: bool,
) -> bool:
    """Return whether a file-based route has an unconsumed completed file.

    API pagination creates one reconciliation-file record per source unit, but
    its runtime run intentionally has no single ``sourceFileId``. Treating
    that missing identifier as a pending file made completed API streams show
    as PENDING after a successful retry.
    """

    if fetch_method == FetchMethod.API or latest_file is None or is_duplicate_outcome:
        return False
    if latest_file.get("processingStatus") != "COMPLETED":
        return False
    return (
        latest_run is None
        or latest_run.source_file_id != latest_file["id"]
        or latest_run.status == PartnerRuntimeRunStatus.WAITING_RECONCILE
    )


def _track_background_task(request: Request, task: asyncio.Task) -> None:
    track_background_task(request.app, task)


async def _run_fetch_job_in_background(db, command: ExecuteStreamCommand) -> None:
    await execute_stream(
        command,
        db=db,
        config_loader=build_config_loader_from_db(db),
        batch_size=100,
        structured_logger=None,
    )


def _workflow_gateway(request: Request, db) -> WorkflowGateway:
    injected = getattr(request.app.state, "workflow_gateway", None)
    if injected is not None:
        return injected
    if settings.automation_orchestrator == "airflow":
        if not settings.airflow_username or not settings.airflow_password:
            raise WorkflowUnavailable("Airflow service credentials are not configured")
        return AirflowWorkflowGateway(
            base_url=settings.airflow_base_url,
            dag_id=settings.airflow_dag_id,
            username=settings.airflow_username,
            password=settings.airflow_password,
            timeout_seconds=settings.airflow_request_timeout_seconds,
        )

    async def run_local(command: ExecuteStreamCommand) -> None:
        await _run_fetch_job_in_background(db, command)

    return LocalWorkflowGateway(
        runner=run_local,
        track_task=lambda task: _track_background_task(request, task),
    )


async def _approved_backfill_mapping_version(db, partner: str) -> str | None:
    raw = await db["reconciliation_mapping_config"].find_one(
        {
            "partner": partner,
            "workflowType": "UPC",
            "fileType": "SETTLEMENT",
            "status": "APPROVED",
        },
        projection={"configVersion": 1},
        sort=[("createdAt", -1)],
    )
    value = (raw or {}).get("configVersion")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


async def _attach_pending_backfill_review_packet(
    db,
    partner: str,
    backfill_run_id: str,
) -> str | None:
    packet = await db["review_packet"].find_one(
        {
            "partner": partner,
            "status": "PENDING",
            "sourceType": "SCHEDULER_JOB",
        },
        projection={"_id": 1},
        sort=[("createdAt", -1)],
    )
    if packet is None:
        return None
    packet_id = str(packet["_id"])
    await db["review_packet"].update_one(
        {"_id": packet_id},
        {"$set": {"backfillRunId": backfill_run_id}},
    )
    return packet_id


def _backfill_service(request: Request, db) -> BackfillRunService:
    return BackfillRunService(
        fetch_repo=FetchConfigRepository(db),
        backfill_repo=BackfillRunRepository(db),
        workflow_gateway=_LazyWorkflowGateway(lambda: _workflow_gateway(request, db)),
        approved_mapping_version_finder=lambda partner: _approved_backfill_mapping_version(db, partner),
        pending_review_packet_finder=lambda partner, run_id: _attach_pending_backfill_review_packet(
            db,
            partner,
            run_id,
        ),
    )


async def _airflow_task_state(request: Request, db, runtime_run_data: dict | None) -> str | None:
    """Best-effort read of the Airflow task backing an application runtime.

    The application runtime can be marked FAILED before Airflow has finished
    its native retry delay.  Reading the task instance lets the API expose the
    real orchestration state and prevents Run now/Retry from queueing a second
    DAG run behind the one that is already waiting for retry.
    """

    if settings.automation_orchestrator != "airflow" or not runtime_run_data:
        return None
    orchestration = runtime_run_data.get("orchestration") or {}
    dag_run_id = orchestration.get("dagRunId")
    if not dag_run_id:
        return None
    try:
        gateway = _workflow_gateway(request, db)
        reader = getattr(gateway, "task_state", None)
        if not callable(reader):
            return None
        value = reader(
            dag_run_id,
            task_id=orchestration.get("taskId") or "run_stream",
            map_index=(
                orchestration["mapIndex"]
                if orchestration.get("mapIndex") is not None
                else 0
            ),
        )
        if inspect.isawaitable(value):
            value = await value
        return str(value).lower() if value is not None else None
    except Exception:
        # Airflow is an optional visibility source for the jobs view.  A
        # temporary outage leaves the persisted runtime visible there; the
        # retry endpoint fails closed when an Airflow run is already attached
        # so it cannot create a duplicate DAG run.
        logger.warning(
            "airflow_task_state_unavailable dagRunId=%s taskId=%s mapIndex=%s",
            dag_run_id,
            orchestration.get("taskId") or "run_stream",
            orchestration.get("mapIndex") if orchestration.get("mapIndex") is not None else 0,
            exc_info=True,
        )
        return None


async def _retry_existing_airflow_run(
    request: Request,
    db,
    latest_run,
    latest_run_data: dict | None,
    task_state: str | None,
    actor: str,
):
    """Clear a retryable task in-place instead of creating another DAG run."""

    if task_state not in _AIRFLOW_MANUAL_RETRY_STATES or not latest_run_data:
        return None
    orchestration = latest_run_data.get("orchestration") or {}
    dag_run_id = orchestration.get("dagRunId")
    if not dag_run_id:
        return None
    gateway = _workflow_gateway(request, db)
    retryer = getattr(gateway, "retry_task", None)
    if not callable(retryer):
        raise WorkflowUnavailable("Airflow gateway does not support in-place task retry")
    result = retryer(
        dag_run_id,
        task_id=orchestration.get("taskId") or "run_stream",
        map_index=(
            orchestration["mapIndex"]
            if orchestration.get("mapIndex") is not None
            else 0
        ),
    )
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, WorkflowSubmission):
        raise WorkflowUnavailable("Airflow task retry returned an invalid submission")
    message = "Manual retry requested in the existing Airflow DAG run."
    retry_event = {
        "eventId": f"{latest_run.id}:manual-retry:{uuid4()}",
        "status": "RETRY_REQUESTED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "message": message,
    }
    await update_runtime_run(
        db,
        str(latest_run.id),
        status=PartnerRuntimeRunStatus.QUEUED,
        message=message,
        stats={"retryable": True, "airflowTaskState": task_state, "retryActor": actor},
        clear_finished_at=True,
        attempt_event=retry_event,
    )
    latest_run.status = PartnerRuntimeRunStatus.QUEUED
    latest_run.message = message
    latest_run.finished_at = None
    latest_run.attempt_history.append(retry_event)
    return {
        "ok": True,
        "queued": True,
        "retried": True,
        "actor": actor,
        "partner": latest_run.partner,
        "message": message,
        "runtimeRunId": str(latest_run.id),
        "resumedFromUnitKey": None,
        "run": serialize_partner_runtime_run(latest_run),
        "workflow": result.model_dump(by_alias=True, mode="json"),
    }


async def _queue_scheduler_run(
    request: Request,
    db,
    config,
    *,
    actor: str,
    message: str,
):
    reconciliation_date = datetime.now(ZoneInfo(settings.business_timezone)).date()
    run = await create_runtime_run(
        db,
        partner=config.partner,
        date=reconciliation_date.isoformat(),
        trigger_type=PartnerRuntimeTriggerType.SCHEDULER,
        triggered_by=actor,
        status=PartnerRuntimeRunStatus.QUEUED,
        message=message,
    )
    command = ExecuteStreamCommand(
        fetchConfigId=str(config.id),
        partner=config.partner,
        configVersion=str(config.updated_at),
        reconciliationDate=reconciliation_date,
        runtimeRunId=str(run.id),
        correlationId=f"runtime:{run.id}",
    )
    try:
        submission = await _workflow_gateway(request, db).trigger(command)
    except WorkflowSubmissionConflict as exc:
        await _mark_submission_failed(db, run, "DAG_RUN_ID_COLLISION")
        raise HTTPException(status_code=409, detail="Workflow run ID collision.") from exc
    except WorkflowUnavailable as exc:
        await _mark_submission_failed(db, run, "ORCHESTRATOR_UNAVAILABLE")
        raise HTTPException(status_code=503, detail="Workflow orchestration is unavailable.") from exc

    if submission.provider == WorkflowProvider.AIRFLOW:
        orchestration = RuntimeOrchestrationContext(
            dagId=submission.workflow_id,
            dagRunId=submission.workflow_run_id,
            taskId="run_stream",
            correlationId=command.correlation_id,
        )
        await update_runtime_run(
            db,
            str(run.id),
            orchestration=orchestration.model_dump(by_alias=True, mode="json"),
        )
        run.orchestration = orchestration
    return run, submission


async def _mark_submission_failed(db, run, error_code: str) -> None:
    message = f"Workflow submission failed ({error_code})."
    await update_runtime_run(
        db,
        str(run.id),
        status=PartnerRuntimeRunStatus.FAILED,
        message=message,
        stats={"errorCode": error_code, "retryable": False},
        finished_at=datetime.now(timezone.utc),
    )


class BackfillStartPayload(BaseModel):
    from_date: date = Field(alias="fromDate")
    to_date: date = Field(alias="toDate")
    fetch_config_id: str | None = Field(default=None, alias="fetchConfigId")


@router.get("/jobs")
async def list_automation_jobs(request: Request):
    db = _get_db(request)
    fetch_repo = FetchConfigRepository(db)
    packet_repo = ReviewPacketRepository(db)
    runtime_run_repo = PartnerRuntimeRunRepository(db)
    checkpoint_repo = IngestionCheckpointRepository(db)
    configs = await fetch_repo.find_enabled()
    checkpoint_identities = [
        {
            "partner": config.partner,
            "fetchConfigId": str(config.id),
            "sourceType": config.fetch_method.value,
            "streamKey": _stream_key_for_config(config),
            "mode": IngestionMode.SCHEDULED,
        }
        for config in configs
    ]
    checkpoints = await checkpoint_repo.find_by_streams(checkpoint_identities)
    checkpoint_by_identity = {
        (
            checkpoint.partner,
            checkpoint.fetch_config_id,
            checkpoint.source_type,
            checkpoint.mode,
        ): checkpoint
        for checkpoint in checkpoints
    }
    max_attempts = RetryPolicy().max_attempts
    packets = await packet_repo.find_many({})
    packets.sort(key=lambda item: item.created_at, reverse=True)
    pending_by_partner: dict[str, int] = {}
    recent_packet_docs: dict[str, list[dict]] = {}
    pending_packet_keys: set[tuple[str, str, str]] = set()
    for packet in packets:
        if packet.source_type.value != "SCHEDULER_JOB":
            continue
        if packet.status.value == "PENDING":
            # A partner/file type has one active mapping proposal. Collapse
            # legacy duplicate packets here so retries cannot surface two
            # operator actions for the same scheduler stream.
            packet_key = (
                packet.partner,
                packet.source_type.value,
                packet.file_type_detected,
            )
            if packet_key in pending_packet_keys:
                continue
            pending_packet_keys.add(packet_key)
            pending_by_partner[packet.partner] = pending_by_partner.get(packet.partner, 0) + 1
        recent_packet_docs.setdefault(packet.partner, []).append({
            "_id": str(packet.id),
            "fileName": packet.file_name,
            "status": packet.status.value,
            "sourceType": packet.source_type.value,
            "decisionMode": packet.decision_mode.value if packet.decision_mode else None,
            "recommendedAction": packet.recommended_action,
            "parseStrategy": packet.parse_strategy,
            "riskSummary": packet.risk_summary,
            "createdAt": packet.created_at.isoformat(),
            "reviewedAt": packet.reviewed_at.isoformat() if packet.reviewed_at else None,
        })
    for partner_packets in recent_packet_docs.values():
        partner_packets.sort(key=lambda item: item["createdAt"], reverse=True)

    jobs = []
    for config in configs:
        method_config = config.get_method_config()
        destination = "-"
        if method_config is not None:
          if hasattr(method_config, "remote_path"):
              destination = getattr(method_config, "remote_path")
          elif hasattr(method_config, "base_url"):
              destination = getattr(method_config, "base_url")
          elif hasattr(method_config, "directory"):
              destination = getattr(method_config, "directory")
        latest_run = await runtime_run_repo.find_latest_by_partner(config.partner)
        recent_runs = await runtime_run_repo.find_recent_by_partner(config.partner, limit=5)
        latest_file_raw = await db["reconciliation_file"].find_one(
            {"partner": config.partner},
            sort=[("createdAt", -1)],
        )
        latest_file = None
        if latest_file_raw is not None:
            latest_file = {
                "id": str(latest_file_raw.get("_id")),
                "fileName": latest_file_raw.get("fileName"),
                "processingStatus": latest_file_raw.get("processingStatus"),
                "reconciliationDate": latest_file_raw.get("reconciliationDate").isoformat() if isinstance(latest_file_raw.get("reconciliationDate"), datetime) else str(latest_file_raw.get("reconciliationDate") or ""),
                "createdAt": latest_file_raw.get("createdAt").isoformat() if isinstance(latest_file_raw.get("createdAt"), datetime) else str(latest_file_raw.get("createdAt") or ""),
            }

        latest_run_data = serialize_partner_runtime_run(latest_run) if latest_run else None
        attempt_history = _merge_runtime_attempt_history(recent_runs, latest_run_data)
        airflow_task_state = await _airflow_task_state(request, db, latest_run_data)
        if latest_run_data is not None and airflow_task_state is not None:
            latest_run_data.setdefault("orchestration", {})["taskState"] = airflow_task_state
        checkpoint = checkpoint_by_identity.get(
            (
                config.partner,
                str(config.id),
                config.fetch_method.value,
                IngestionMode.SCHEDULED,
            )
        )
        latest_run_stats = (latest_run_data or {}).get("stats") or {}
        duplicate_outcome = latest_run_stats.get("outcome")
        if duplicate_outcome is None and latest_run_stats.get("replayed", 0) > 0:
            duplicate_outcome = "FETCH_UNIT_REPLAY"
        is_duplicate_outcome = duplicate_outcome in {
            "FILE_DUPLICATE",
            "FETCH_UNIT_REPLAY",
            "NO_NEW_FILE",
        }
        airflow_retry_active = airflow_task_state in _AIRFLOW_RETRYING_TASK_STATES
        airflow_terminal_retry = airflow_task_state in _AIRFLOW_MANUAL_RETRY_STATES
        application_runtime_active = latest_run_data and latest_run_data.get("status") in _ACTIVE_RUNTIME_STATUSES
        active_run = (
            latest_run_data
            if latest_run_data
            and (
                (application_runtime_active and not airflow_terminal_retry)
                or airflow_retry_active
            )
            else None
        )
        has_pending_file = _has_pending_file(
            fetch_method=config.fetch_method,
            latest_file=latest_file,
            latest_run=latest_run,
            is_duplicate_outcome=is_duplicate_outcome,
        )
        status = "HEALTHY"
        status_message = "No active runtime work."
        if airflow_retry_active:
            status = "RETRYING"
            status_message = "Airflow is retrying this run; wait for it to finish before starting another run."
        elif active_run:
            status = active_run.get("status") or "RUNNING"
            status_message = active_run.get("message") or "Runtime flow is active."
        elif latest_run_data and latest_run_data.get("status") == PartnerRuntimeRunStatus.FAILED.value:
            status = "FAILED"
            status_message = latest_run_data.get("message") or "Latest runtime run failed."
        elif airflow_terminal_retry:
            status = "FAILED"
            status_message = "Airflow task failed; Retry will clear the task in the existing DAG run."
        elif is_duplicate_outcome:
            status_message = {
                "FILE_DUPLICATE": "File already processed. Ingestion and reconciliation were skipped safely.",
                "FETCH_UNIT_REPLAY": "Fetch unit already processed. Ingestion and reconciliation were skipped safely.",
                "NO_NEW_FILE": "No new file was found. Ingestion and reconciliation were skipped.",
            }[duplicate_outcome]
        elif has_pending_file:
            status = "PENDING"
            status_message = "A partner file is available and waiting for reconciliation."
        jobs.append({
            "partner": config.partner,
            "fetchMethod": config.fetch_method.value,
            "schedule": config.schedule,
            "enabled": config.enabled,
            "localDownloadDir": config.local_download_dir,
            "destination": destination,
            "pendingReviewPackets": pending_by_partner.get(config.partner, 0),
            "updatedAt": config.updated_at.isoformat() if isinstance(config.updated_at, datetime) else str(config.updated_at),
            "recentPackets": recent_packet_docs.get(config.partner, [])[:3],
            "status": status,
            "statusMessage": status_message,
            "duplicateOutcome": duplicate_outcome,
            "duplicateMessage": status_message if is_duplicate_outcome else None,
            "hasPendingFile": has_pending_file,
            "latestRuntimeRun": latest_run_data,
            "recentRuntimeRuns": [
                serialize_partner_runtime_run(item) for item in recent_runs
            ],
            "activeRuntimeRun": active_run,
            "latestFile": latest_file,
            "recovery": build_recovery_view(
                checkpoint=checkpoint,
                latest_run=latest_run_data,
                max_attempts=max_attempts,
                attempt_history=attempt_history,
                expected_unit_count=(
                    getattr(method_config.pagination, "max_pages", None)
                    if config.fetch_method.value == "API"
                    and getattr(method_config, "pagination", None) is not None
                    else None
                ),
            ),
        })
    return {"jobs": jobs}


@router.post("/jobs/{partner}/run")
async def run_automation_job_now(request: Request, partner: str):
    actor = require_actor(request, payload_field_name="actor")
    db = _get_db(request)
    fetch_repo = FetchConfigRepository(db)
    config = await fetch_repo.find_by_partner(partner)
    if config is None:
        raise HTTPException(status_code=404, detail="Automation job not found for partner.")
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Automation job is disabled.")

    checkpoint_repo = IngestionCheckpointRepository(db)
    checkpoint = await _find_recovery_checkpoint(checkpoint_repo, config)
    latest_run = await PartnerRuntimeRunRepository(db).find_latest_by_partner(partner)
    latest_run_data = serialize_partner_runtime_run(latest_run) if latest_run else None
    airflow_task_state = await _airflow_task_state(request, db, latest_run_data)
    if airflow_task_state in _AIRFLOW_RETRYING_TASK_STATES:
        raise HTTPException(
            status_code=409,
            detail="Airflow is already retrying this run; wait for the native retry to finish before running again.",
        )
    if latest_run is not None and getattr(latest_run.status, "value", latest_run.status) in _ACTIVE_RUNTIME_STATUSES:
        raise HTTPException(status_code=409, detail="An Airflow/runtime attempt is already active; wait for it to finish or retry.")
    if checkpoint is not None and _has_live_claim(checkpoint):
        raise HTTPException(status_code=409, detail="Recovery is already processing a live source-unit claim.")
    if checkpoint is not None:
        if checkpoint.status == "BLOCKED":
            raise HTTPException(
                status_code=409,
                detail="Checkpoint is BLOCKED and requires operator resolution before starting a new run.",
            )
        if _checkpoint_waiting_for_mapping_review(checkpoint):
            pending_review = await db["review_packet"].find_one(
                {
                    "partner": partner,
                    "sourceType": "SCHEDULER_JOB",
                    "status": "PENDING",
                },
                projection={"_id": 1},
            )
            if pending_review is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Checkpoint is waiting for mapping review; approve the review packet before running again.",
                )
        if checkpoint.status == "FAILED":
            if checkpoint.retryable is not True:
                raise HTTPException(
                    status_code=409,
                    detail="Checkpoint failure is terminal and cannot be retried from Run now.",
                )
            prepared = await checkpoint_repo.prepare_manual_retry(
                checkpoint,
                operator_id=actor,
                reason="Operator requested immediate run for a retryable checkpoint",
            )
            if not prepared:
                raise HTTPException(
                    status_code=409,
                    detail="Checkpoint changed before Run now could prepare the retry.",
                )

    run, submission = await _queue_scheduler_run(
        request,
        db,
        config,
        actor=actor,
        message="Automation run queued. Watch runtime state for live progress.",
    )
    return {
        "ok": True,
        "queued": True,
        "actor": actor,
        "partner": partner,
        "message": "Automation run queued. Watch runtime state for live progress.",
        "runtimeRunId": str(run.id),
        "run": serialize_partner_runtime_run(run),
        "workflow": submission.model_dump(by_alias=True, mode="json"),
    }


@router.post("/jobs/{partner}/backfill")
async def start_backfill(request: Request, partner: str, payload: BackfillStartPayload):
    actor = require_actor(request, payload_field_name="actor")
    db = _get_db(request)
    service = _backfill_service(request, db)
    try:
        run = await service.start(
            partner=partner,
            actor=actor,
            from_date=payload.from_date,
            to_date=payload.to_date,
            fetch_config_id=payload.fetch_config_id,
        )
    except BackfillRunError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return serialize_backfill_run(run)


@router.get("/backfill-runs/{backfill_run_id}")
async def get_backfill_run(request: Request, backfill_run_id: str):
    db = _get_db(request)
    service = _backfill_service(request, db)
    try:
        run = await service.get(backfill_run_id)
    except BackfillRunError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return serialize_backfill_run(run)


@router.post("/jobs/{partner}/recovery/retry")
async def retry_automation_job(request: Request, partner: str):
    actor = require_actor(request, payload_field_name="actor")
    db = _get_db(request)
    fetch_repo = FetchConfigRepository(db)
    config = await fetch_repo.find_by_partner(partner)
    if config is None:
        raise HTTPException(status_code=404, detail="Automation job not found for partner.")
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Automation job is disabled.")

    checkpoint_repo = IngestionCheckpointRepository(db)
    checkpoint = await _find_recovery_checkpoint(checkpoint_repo, config)
    latest_run = await PartnerRuntimeRunRepository(db).find_latest_by_partner(partner)
    latest_run_data = serialize_partner_runtime_run(latest_run) if latest_run else None
    airflow_task_state = await _airflow_task_state(request, db, latest_run_data)
    orchestration = (latest_run_data or {}).get("orchestration") or {}
    has_existing_airflow_run = (
        settings.automation_orchestrator == "airflow"
        and bool(orchestration.get("dagRunId"))
    )
    if has_existing_airflow_run and airflow_task_state not in _AIRFLOW_MANUAL_RETRY_STATES:
        state = airflow_task_state or "unknown"
        raise HTTPException(
            status_code=409,
            detail=(
                f"Existing Airflow DAG run is not manually retryable (task state: {state}); "
                "no new Airflow DAG run was created."
            ),
        )
    if (
        latest_run is not None
        and getattr(latest_run.status, "value", latest_run.status) in _ACTIVE_RUNTIME_STATUSES
        and airflow_task_state not in _AIRFLOW_MANUAL_RETRY_STATES
    ):
        raise HTTPException(status_code=409, detail="An Airflow/runtime retry is already active; wait for it to finish.")
    if checkpoint is None:
        try:
            existing_retry = await _retry_existing_airflow_run(
                request,
                db,
                latest_run,
                latest_run_data,
                airflow_task_state,
                actor,
            ) if latest_run is not None else None
        except WorkflowUnavailable as exc:
            raise HTTPException(status_code=503, detail="Airflow task retry is unavailable.") from exc
        if existing_retry is not None:
            return existing_retry
        # A fetch can fail before the first source unit is claimed (the
        # durable-staging path deliberately does not claim partial streams).
        # There is then no checkpoint to resume, but a manual retry is still
        # safe: it starts a fresh fetch and reuses any idempotently staged raw
        # pages instead of making the operator fall back to Run now.
        run, submission = await _queue_scheduler_run(
            request,
            db,
            config,
            actor=actor,
            message="Retry queued after a fetch failure before checkpoint creation.",
        )
        return {
            "ok": True,
            "queued": True,
            "actor": actor,
            "partner": partner,
            "message": "Retry queued after a fetch failure before checkpoint creation.",
            "runtimeRunId": str(run.id),
            "resumedFromUnitKey": None,
            "run": serialize_partner_runtime_run(run),
            "workflow": submission.model_dump(by_alias=True, mode="json"),
        }
    if _has_live_claim(checkpoint):
        raise HTTPException(status_code=409, detail="Recovery is already processing a live source-unit claim.")
    if checkpoint.status == "BLOCKED":
        raise HTTPException(status_code=409, detail="Checkpoint is BLOCKED and requires operator resolution before retry.")
    if checkpoint.status == "FAILED":
        if checkpoint.retryable is not True:
            raise HTTPException(status_code=409, detail="Checkpoint failure is terminal and cannot be retried.")
        prepared = await checkpoint_repo.prepare_manual_retry(
            checkpoint,
            operator_id=actor,
            reason="Operator requested immediate recovery retry",
        )
        if not prepared:
            raise HTTPException(status_code=409, detail="Checkpoint changed before recovery retry could be claimed.")
    elif checkpoint.status == "DISCOVERED":
        if (checkpoint.resolution_metadata or {}).get("action") != "RETRY":
            raise HTTPException(status_code=409, detail="Checkpoint is waiting for review or operator resolution.")
    elif checkpoint.status != "PROCESSING":
        raise HTTPException(status_code=409, detail=f"Checkpoint status {checkpoint.status} is not recoverable.")

    try:
        existing_retry = await _retry_existing_airflow_run(
            request,
            db,
            latest_run,
            latest_run_data,
            airflow_task_state,
            actor,
        ) if latest_run is not None else None
    except WorkflowUnavailable as exc:
        raise HTTPException(status_code=503, detail="Airflow task retry is unavailable.") from exc
    if existing_retry is not None:
        return existing_retry

    run, submission = await _queue_scheduler_run(
        request,
        db,
        config,
        actor=actor,
        message="Recovery retry queued from checkpoint.",
    )
    return {
        "ok": True,
        "queued": True,
        "actor": actor,
        "partner": partner,
        "message": "Recovery retry queued from checkpoint.",
        "runtimeRunId": str(run.id),
        "resumedFromUnitKey": checkpoint.current_unit_key,
        "run": serialize_partner_runtime_run(run),
        "workflow": submission.model_dump(by_alias=True, mode="json"),
    }


@router.post("/jobs/{partner}/recovery/resolve")
async def resolve_automation_recovery(request: Request, partner: str):
    actor = require_actor(request, payload_field_name="actor")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Recovery resolution payload must be valid JSON.") from exc
    action = str(payload.get("action") or "").upper()
    reason = str(payload.get("reason") or "").strip()
    if action not in {"RETRY", "SKIP"}:
        raise HTTPException(status_code=400, detail="Recovery action must be RETRY or SKIP.")
    if not reason:
        raise HTTPException(status_code=400, detail="A reason is required for recovery resolution.")
    if len(reason) > 500:
        raise HTTPException(status_code=400, detail="Recovery reason must be 500 characters or fewer.")

    db = _get_db(request)
    fetch_repo = FetchConfigRepository(db)
    config = await fetch_repo.find_by_partner(partner)
    if config is None:
        raise HTTPException(status_code=404, detail="Automation job not found for partner.")
    checkpoint_repo = IngestionCheckpointRepository(db)
    checkpoint = await _find_recovery_checkpoint(checkpoint_repo, config)
    if checkpoint is None or checkpoint.status != "BLOCKED" or not checkpoint.current_unit_key:
        raise HTTPException(status_code=409, detail="Only a BLOCKED checkpoint with a current unit can be resolved.")

    unit_key = checkpoint.current_unit_key
    resolved = await checkpoint_repo.resolve_blocked(
        checkpoint,
        unit_key=unit_key,
        action=action,
        reason=reason,
        operator_id=actor,
    )
    if not resolved:
        raise HTTPException(status_code=409, detail="Checkpoint changed before recovery resolution was applied.")

    await record_audit_event(
        db,
        entity_type="INGESTION_CHECKPOINT",
        entity_id=f"{config.partner}:{config.fetch_method.value}:scheduled",
        action=f"RECOVERY_{action}",
        actor=actor,
        metadata={
            "partner": config.partner,
            "unitKey": unit_key,
            "reason": reason,
            "action": action,
        },
    )
    return {
        "ok": True,
        "actor": actor,
        "partner": config.partner,
        "action": action,
        "unitKey": unit_key,
        "status": "DISCOVERED",
        "message": f"Recovery checkpoint resolved with action {action}.",
    }
