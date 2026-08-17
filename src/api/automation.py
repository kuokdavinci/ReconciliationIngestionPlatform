"""Automation visibility endpoints for scheduler/admin views."""

import asyncio
import inspect
import logging
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.actor import require_actor
from src.api.dependencies import get_request_db as _get_db
from src.application.automation import ExecuteStreamCommand, execute_stream
from src.application.automation.job_commands import AutomationJobCommandService
from src.application.automation.job_contracts import (
    AutomationApplicationError,
    AutomationConflictError,
    AutomationNotFoundError,
    AutomationUnavailableError,
    AutomationValidationError,
    ResolveAutomationRecoveryCommand,
    RetryAutomationJobCommand,
    RunAutomationJobCommand,
)
from src.application.automation.job_queries import AutomationJobQueryService
from src.application.automation.stream_identity import raw_stage_key, source_stream_key
from src.application.automation.workflows import (
    WorkflowGateway,
    WorkflowSubmission,
    WorkflowUnavailable,
)
from src.config.settings import settings
from src.domain.fetch_config.models import FetchMethod
from src.domain.ingestion.checkpoints import IngestionMode
from src.infrastructure.backfill.repository import BackfillRunRepository
from src.infrastructure.fetch_config.repository import FetchConfigRepository
from src.infrastructure.ingestion.checkpoint_repository import IngestionCheckpointRepository
from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository
from src.domain.runtime.models import (
    PartnerRuntimeRunStatus,
)
from src.infrastructure.runtime.repository import PartnerRuntimeRunRepository
from src.infrastructure.review.repository import ReviewPacketRepository
from src.application.automation.backfill_service import (
    BackfillRunConflictError,
    BackfillRunError,
    BackfillRunNotFoundError,
    BackfillRunService,
    BackfillRunUnavailableError,
    BackfillRunValidationError,
    serialize_backfill_run,
)
from src.application.runtime.service import serialize_partner_runtime_run
from src.application.audit.service import record_audit_event
from src.infrastructure.mapping.composition import build_config_loader
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
_BACKFILL_ERROR_STATUS: dict[type[BackfillRunError], int] = {
    BackfillRunValidationError: 400,
    BackfillRunNotFoundError: 404,
    BackfillRunConflictError: 409,
    BackfillRunUnavailableError: 503,
}


def _backfill_error_status(error: BackfillRunError) -> int:
    for error_type, status_code in _BACKFILL_ERROR_STATUS.items():
        if isinstance(error, error_type):
            return status_code
    return 400


class _LazyWorkflowGateway:
    """Resolve the workflow adapter only when a run is actually submitted."""

    def __init__(self, factory):
        self._factory = factory
        self._gateway: WorkflowGateway | None = None

    async def trigger(self, command: ExecuteStreamCommand) -> WorkflowSubmission:
        if self._gateway is None:
            self._gateway = self._factory()
        return await self._gateway.trigger(command)

    async def retry_task(self, *args, **kwargs):
        if self._gateway is None:
            self._gateway = self._factory()
        retryer = getattr(self._gateway, "retry_task", None)
        if not callable(retryer):
            raise WorkflowUnavailable("Workflow gateway does not support in-place task retry")
        result = retryer(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result


def _stream_key_for_config(config) -> str | None:
    try:
        return source_stream_key(config)
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
        config_loader=build_config_loader(db),
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
    from datetime import date, datetime, time
    from zoneinfo import ZoneInfo

    from src.core.business_day import business_day_bounds

    backfill_run = await db["backfill_run"].find_one(
        {"_id": backfill_run_id},
        projection={"currentDate": 1},
    )
    date_filter: dict[str, dict[str, datetime]] = {}
    current_date = (backfill_run or {}).get("currentDate")
    if current_date:
        if isinstance(current_date, datetime):
            current_date = current_date.date()
        elif not isinstance(current_date, date):
            current_date = date.fromisoformat(str(current_date)[:10])
        business_timezone = ZoneInfo(settings.business_timezone)
        start_of_day, end_of_day = business_day_bounds(
            datetime.combine(current_date, time.min, tzinfo=business_timezone)
        )
        date_filter = {
            "reconciliationDate": {
                "$gte": start_of_day,
                "$lte": end_of_day,
            }
        }
    packet = await db["review_packet"].find_one(
        {
            "partner": partner,
            "status": "PENDING",
            "sourceType": "SCHEDULER_JOB",
            **date_filter,
        },
        projection={"_id": 1},
        sort=[("createdAt", -1)],
    )
    if packet is None:
        return None
    packet_backfill_run_id = packet.get("backfillRunId")
    if packet_backfill_run_id and str(packet_backfill_run_id) != backfill_run_id:
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




def _automation_error_status(error: AutomationApplicationError) -> int:
    if isinstance(error, AutomationNotFoundError):
        return 404
    if isinstance(error, AutomationValidationError):
        return 400
    if isinstance(error, AutomationConflictError):
        return 409
    if isinstance(error, AutomationUnavailableError):
        return 503
    return 400


def _job_query_service(request: Request, db) -> AutomationJobQueryService:
    async def task_state_resolver(runtime_run_data):
        return await _airflow_task_state(request, db, runtime_run_data)

    return AutomationJobQueryService(
        db=db,
        fetch_repo=FetchConfigRepository(db),
        packet_repo=ReviewPacketRepository(db),
        runtime_run_repo=PartnerRuntimeRunRepository(db),
        checkpoint_repo=IngestionCheckpointRepository(db),
        backfill_repo=BackfillRunRepository(db),
        task_state_resolver=task_state_resolver,
    )


def _job_command_service(request: Request, db) -> AutomationJobCommandService:
    checkpoint_repo = IngestionCheckpointRepository(db)

    async def checkpoint_finder(config):
        return await _find_recovery_checkpoint(checkpoint_repo, config)

    async def task_state_resolver(runtime_run_data):
        return await _airflow_task_state(request, db, runtime_run_data)

    async def pending_review_finder(partner: str) -> bool:
        pending_review = await db["review_packet"].find_one(
            {
                "partner": partner,
                "sourceType": "SCHEDULER_JOB",
                "status": "PENDING",
            },
            projection={"_id": 1},
        )
        return pending_review is not None

    async def completed_stream_finder(config) -> bool:
        if config.fetch_method != FetchMethod.API:
            return False
        reconciliation_date = datetime.now(ZoneInfo(settings.business_timezone))
        stage_key = raw_stage_key(config, reconciliation_date)
        completed_file = await ReconciliationFileRepository(
            db
        ).find_completed_by_raw_stage_key(stage_key)
        return completed_file is not None

    async def audit_recorder(*, config, action, actor, metadata):
        await record_audit_event(
            db,
            entity_type="INGESTION_CHECKPOINT",
            entity_id=f"{config.partner}:{config.fetch_method.value}:scheduled",
            action=action,
            actor=actor,
            metadata=metadata,
        )

    return AutomationJobCommandService(
        fetch_repo=FetchConfigRepository(db),
        backfill_repo=BackfillRunRepository(db),
        runtime_repo=PartnerRuntimeRunRepository(db),
        checkpoint_repo=checkpoint_repo,
        workflow_gateway=_LazyWorkflowGateway(lambda: _workflow_gateway(request, db)),
        runtime_service=SimpleNamespace(
            serialize_partner_runtime_run=serialize_partner_runtime_run
        ),
        checkpoint_finder=checkpoint_finder,
        task_state_resolver=task_state_resolver,
        pending_review_finder=pending_review_finder,
        completed_stream_finder=completed_stream_finder,
        audit_recorder=audit_recorder,
    )


async def _recovery_resolution_payload(request: Request) -> tuple[str, str]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Recovery resolution payload must be valid JSON.",
        ) from exc
    action = str(payload.get("action") or "").upper()
    reason = str(payload.get("reason") or "").strip()
    if action not in {"RETRY", "SKIP"}:
        raise HTTPException(status_code=400, detail="Recovery action must be RETRY or SKIP.")
    if not reason:
        raise HTTPException(status_code=400, detail="A reason is required for recovery resolution.")
    if len(reason) > 500:
        raise HTTPException(
            status_code=400,
            detail="Recovery reason must be 500 characters or fewer.",
        )
    return action, reason


class BackfillStartPayload(BaseModel):
    from_date: date = Field(alias="fromDate")
    to_date: date = Field(alias="toDate")
    fetch_config_id: str | None = Field(default=None, alias="fetchConfigId")




@router.get("/jobs")
async def list_automation_jobs(request: Request):
    db = _get_db(request)
    service = _job_query_service(request, db)
    return {"jobs": await service.list_jobs()}



@router.post("/jobs/{partner}/run")
async def run_automation_job_now(request: Request, partner: str):
    actor = require_actor(request, payload_field_name="actor")
    db = _get_db(request)
    service = _job_command_service(request, db)
    try:
        return await service.run_now(
            RunAutomationJobCommand(partner=partner, actor=actor)
        )
    except AutomationApplicationError as exc:
        raise HTTPException(
            status_code=_automation_error_status(exc),
            detail=str(exc),
        ) from exc


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
        raise HTTPException(status_code=_backfill_error_status(exc), detail=str(exc)) from exc
    return serialize_backfill_run(run)


@router.get("/backfill-runs/{backfill_run_id}")
async def get_backfill_run(request: Request, backfill_run_id: str):
    db = _get_db(request)
    service = _backfill_service(request, db)
    try:
        run = await service.get(backfill_run_id)
    except BackfillRunError as exc:
        raise HTTPException(status_code=_backfill_error_status(exc), detail=str(exc)) from exc
    return serialize_backfill_run(run)




@router.post("/jobs/{partner}/recovery/retry")
async def retry_automation_job(request: Request, partner: str):
    actor = require_actor(request, payload_field_name="actor")
    db = _get_db(request)
    service = _job_command_service(request, db)
    try:
        return await service.retry(
            RetryAutomationJobCommand(partner=partner, actor=actor)
        )
    except AutomationApplicationError as exc:
        raise HTTPException(
            status_code=_automation_error_status(exc),
            detail=str(exc),
        ) from exc


@router.post("/jobs/{partner}/recovery/resolve")
async def resolve_automation_recovery(request: Request, partner: str):
    actor = require_actor(request, payload_field_name="actor")
    action, reason = await _recovery_resolution_payload(request)
    db = _get_db(request)
    service = _job_command_service(request, db)
    try:
        return await service.resolve(
            ResolveAutomationRecoveryCommand(
                partner=partner,
                actor=actor,
                action=action,
                reason=reason,
            )
        )
    except AutomationApplicationError as exc:
        raise HTTPException(
            status_code=_automation_error_status(exc),
            detail=str(exc),
        ) from exc
