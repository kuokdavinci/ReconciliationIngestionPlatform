"""Application services for automation run and recovery commands."""

import inspect
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from src.application.automation.contracts import ExecuteStreamCommand
from src.application.automation.job_contracts import (
    AutomationConflictError,
    AutomationNotFoundError,
    AutomationUnavailableError,
    AutomationValidationError,
    ResolveAutomationRecoveryCommand,
    RetryAutomationJobCommand,
    RunAutomationJobCommand,
)
from src.application.automation.workflows import (
    WorkflowSubmission,
    WorkflowSubmissionConflict,
    WorkflowUnavailable,
)
from src.config.settings import settings
from src.domain.runtime.models import (
    PartnerRuntimeRun,
    PartnerRuntimeRunStatus,
    PartnerRuntimeTriggerType,
    RuntimeOrchestrationContext,
)


class AutomationJobCommandService:
    """Execute automation commands against injected persistence/workflow ports."""

    _ACTIVE_RUNTIME_STATUSES = {
        PartnerRuntimeRunStatus.QUEUED.value,
        PartnerRuntimeRunStatus.FETCHING.value,
        PartnerRuntimeRunStatus.INGESTING.value,
        PartnerRuntimeRunStatus.WAITING_REVIEW.value,
        PartnerRuntimeRunStatus.WAITING_RECONCILE.value,
        PartnerRuntimeRunStatus.RECONCILING.value,
    }
    _AIRFLOW_RETRYING_TASK_STATES = {"up_for_retry"}
    _AIRFLOW_MANUAL_RETRY_STATES = {"failed", "upstream_failed", "up_for_retry"}

    def __init__(
        self,
        *,
        fetch_repo,
        backfill_repo,
        runtime_repo,
        checkpoint_repo,
        workflow_gateway,
        runtime_service,
        checkpoint_finder: Callable[[Any], Awaitable[Any | None]] | None = None,
        task_state_resolver: Callable[
            [dict[str, Any] | None], Awaitable[str | None]
        ]
        | None = None,
        queue_run: Callable[[Any, str, str], Awaitable[dict[str, Any]]] | None = None,
        pending_review_finder: Callable[[str], Awaitable[bool]] | None = None,
        audit_recorder: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        self.fetch_repo = fetch_repo
        self.backfill_repo = backfill_repo
        self.runtime_repo = runtime_repo
        self.checkpoint_repo = checkpoint_repo
        self.workflow_gateway = workflow_gateway
        self.runtime_service = runtime_service
        self.checkpoint_finder = checkpoint_finder
        self.task_state_resolver = task_state_resolver
        self.queue_run = queue_run
        self.pending_review_finder = pending_review_finder
        self.audit_recorder = audit_recorder

    async def _config_for_partner(self, partner: str):
        config = await self.fetch_repo.find_by_partner(partner)
        if config is None:
            raise AutomationNotFoundError("Automation job not found for partner.")
        if not config.enabled:
            raise AutomationValidationError("Automation job is disabled.")
        return config

    async def _checkpoint_for_config(self, config):
        if self.checkpoint_finder is None:
            return None
        return await self.checkpoint_finder(config)

    async def _task_state(self, latest_run_data: dict[str, Any] | None) -> str | None:
        if self.task_state_resolver is None:
            return None
        value = await self.task_state_resolver(latest_run_data)
        return str(value).lower() if value is not None else None

    def _serialize_run(self, run) -> dict[str, Any]:
        return self.runtime_service.serialize_partner_runtime_run(run)

    @staticmethod
    def _status(value: Any) -> str:
        return str(getattr(value, "value", value))

    @staticmethod
    def _has_live_claim(checkpoint: Any) -> bool:
        if AutomationJobCommandService._status(checkpoint.status) != "PROCESSING":
            return False
        started_at = getattr(checkpoint, "started_at", None)
        if started_at is None:
            return True
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        return started_at > datetime.now(timezone.utc) - timedelta(seconds=900)

    @classmethod
    def _waiting_for_review(cls, checkpoint: Any) -> bool:
        if cls._status(checkpoint.status) != "DISCOVERED":
            return False
        if getattr(checkpoint, "error_code", None) == "configuration_approval_required":
            return True
        return any(
            cls._status(getattr(unit, "status", None)) == "WAITING_REVIEW"
            for unit in (getattr(checkpoint, "unit_timeline", None) or [])
        )

    async def _latest_runtime(self, partner: str) -> tuple[Any | None, dict[str, Any] | None, str | None]:
        latest_run = await self.runtime_repo.find_latest_by_partner(partner)
        latest_run_data = self._serialize_run(latest_run) if latest_run is not None else None
        return latest_run, latest_run_data, await self._task_state(latest_run_data)

    async def _prepare_retry_if_needed(self, checkpoint, *, actor: str, reason: str) -> None:
        prepared = await self.checkpoint_repo.prepare_manual_retry(
            checkpoint,
            operator_id=actor,
            reason=reason,
        )
        if not prepared:
            raise AutomationConflictError("Checkpoint changed before recovery retry could be claimed.")

    async def _retry_existing_workflow(
        self,
        latest_run,
        latest_run_data: dict[str, Any] | None,
        task_state: str | None,
        actor: str,
    ) -> dict[str, Any] | None:
        if task_state not in self._AIRFLOW_MANUAL_RETRY_STATES or not latest_run_data:
            return None
        orchestration = latest_run_data.get("orchestration") or {}
        dag_run_id = orchestration.get("dagRunId")
        if not dag_run_id:
            return None
        retryer = getattr(self.workflow_gateway, "retry_task", None)
        if not callable(retryer):
            raise AutomationUnavailableError("Airflow task retry is unavailable.")
        result = retryer(
            dag_run_id,
            task_id=orchestration.get("taskId") or "run_stream",
            map_index=orchestration.get("mapIndex", 0),
        )
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, WorkflowSubmission):
            raise AutomationUnavailableError("Airflow task retry returned an invalid submission.")

        message = "Manual retry requested in the existing Airflow DAG run."
        retry_event = {
            "eventId": f"{latest_run.id}:manual-retry:{uuid4()}",
            "status": "RETRY_REQUESTED",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "message": message,
        }
        await self.runtime_repo.update_fields(
            str(latest_run.id),
            {
                "status": PartnerRuntimeRunStatus.QUEUED.value,
                "message": message,
                "stats": {
                    "retryable": True,
                    "airflowTaskState": task_state,
                    "retryActor": actor,
                },
                "finishedAt": None,
                "updatedAt": datetime.now(timezone.utc),
            },
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
            "run": self._serialize_run(latest_run),
            "workflow": result.model_dump(by_alias=True, mode="json"),
        }

    async def _mark_submission_failed(self, run, error_code: str) -> None:
        await self.runtime_repo.update_fields(
            str(run.id),
            {
                "status": PartnerRuntimeRunStatus.FAILED.value,
                "message": f"Workflow submission failed ({error_code}).",
                "stats": {"errorCode": error_code, "retryable": False},
                "finishedAt": datetime.now(timezone.utc),
                "updatedAt": datetime.now(timezone.utc),
            },
        )

    async def _queue_new_run(self, config, *, actor: str, message: str) -> dict[str, Any]:
        if self.queue_run is not None:
            return await self.queue_run(config, actor, message)

        reconciliation_date = datetime.now(
            ZoneInfo(settings.business_timezone)
        ).date()
        run = PartnerRuntimeRun(
            partner=config.partner,
            date=reconciliation_date.isoformat(),
            triggerType=PartnerRuntimeTriggerType.SCHEDULER,
            triggeredBy=actor,
            status=PartnerRuntimeRunStatus.QUEUED,
            message=message,
        )
        run = await self.runtime_repo.create(run)
        command = ExecuteStreamCommand(
            fetchConfigId=str(config.id),
            partner=config.partner,
            configVersion=str(config.updated_at),
            reconciliationDate=reconciliation_date,
            runtimeRunId=str(run.id),
            correlationId=f"runtime:{run.id}",
        )
        try:
            submission = await self.workflow_gateway.trigger(command)
        except WorkflowSubmissionConflict as exc:
            await self._mark_submission_failed(run, "DAG_RUN_ID_COLLISION")
            raise AutomationConflictError("Workflow run ID collision.") from exc
        except WorkflowUnavailable as exc:
            await self._mark_submission_failed(run, "ORCHESTRATOR_UNAVAILABLE")
            raise AutomationUnavailableError("Workflow orchestration is unavailable.") from exc

        if self._status(submission.provider) == "AIRFLOW":
            orchestration = RuntimeOrchestrationContext(
                dagId=submission.workflow_id,
                dagRunId=submission.workflow_run_id,
                taskId="run_stream",
                correlationId=command.correlation_id,
            )
            await self.runtime_repo.update_fields(
                str(run.id),
                {"orchestration": orchestration.model_dump(by_alias=True, mode="json")},
            )
            run.orchestration = orchestration
        return {
            "ok": True,
            "queued": True,
            "actor": actor,
            "partner": config.partner,
            "message": message,
            "runtimeRunId": str(run.id),
            "run": self._serialize_run(run),
            "workflow": submission.model_dump(by_alias=True, mode="json"),
        }

    async def run_now(self, command: RunAutomationJobCommand) -> dict[str, Any]:
        config = await self._config_for_partner(command.partner)
        active_backfill = await self.backfill_repo.find_latest_active_by_partner(command.partner)
        if active_backfill is not None:
            status = self._status(active_backfill.status)
            checkpoint = (
                active_backfill.current_date.isoformat()
                if getattr(active_backfill, "current_date", None)
                else "the current checkpoint"
            )
            raise AutomationConflictError(
                f"Backfill is {status} at {checkpoint}; continue this partner from the Backfill action instead of Run now."
            )

        _, latest_run_data, airflow_task_state = await self._latest_runtime(command.partner)
        if airflow_task_state in self._AIRFLOW_RETRYING_TASK_STATES:
            raise AutomationConflictError(
                "Airflow is already retrying this run; wait for the native retry to finish before running again."
            )
        if latest_run_data and latest_run_data.get("status") in self._ACTIVE_RUNTIME_STATUSES:
            raise AutomationConflictError(
                "An Airflow/runtime attempt is already active; wait for it to finish or retry."
            )

        checkpoint = await self._checkpoint_for_config(config)
        if checkpoint is not None and self._has_live_claim(checkpoint):
            raise AutomationConflictError("Recovery is already processing a live source-unit claim.")
        if checkpoint is not None:
            status = self._status(checkpoint.status)
            if status == "BLOCKED":
                raise AutomationConflictError(
                    "Checkpoint is BLOCKED and requires operator resolution before starting a new run."
                )
            waiting_for_review = self._waiting_for_review(checkpoint)
            if waiting_for_review and self.pending_review_finder is not None:
                waiting_for_review = await self.pending_review_finder(command.partner)
            if waiting_for_review:
                raise AutomationConflictError(
                    "Checkpoint is waiting for mapping review; approve the review packet before running again."
                )
            if status == "FAILED":
                if getattr(checkpoint, "retryable", None) is not True:
                    raise AutomationConflictError(
                        "Checkpoint failure is terminal and cannot be retried from Run now."
                    )
                await self._prepare_retry_if_needed(
                    checkpoint,
                    actor=command.actor,
                    reason="Operator requested immediate run for a retryable checkpoint",
                )

        return await self._queue_new_run(
            config,
            actor=command.actor,
            message="Automation run queued. Watch runtime state for live progress.",
        )

    async def retry(self, command: RetryAutomationJobCommand) -> dict[str, Any]:
        config = await self._config_for_partner(command.partner)
        active_backfill = await self.backfill_repo.find_latest_active_by_partner(command.partner)
        if active_backfill is not None:
            raise AutomationConflictError(
                f"Backfill is {self._status(active_backfill.status)}; retry the Backfill action instead."
            )

        latest_run, latest_run_data, airflow_task_state = await self._latest_runtime(command.partner)
        has_existing_airflow_run = bool(
            latest_run_data
            and (latest_run_data.get("orchestration") or {}).get("dagRunId")
        )
        if has_existing_airflow_run and airflow_task_state not in self._AIRFLOW_MANUAL_RETRY_STATES:
            state = airflow_task_state or "unknown"
            raise AutomationConflictError(
                f"Existing Airflow DAG run is not manually retryable (task state: {state}); no new Airflow DAG run was created."
            )
        if (
            latest_run_data
            and latest_run_data.get("status") in self._ACTIVE_RUNTIME_STATUSES
            and airflow_task_state not in self._AIRFLOW_MANUAL_RETRY_STATES
        ):
            raise AutomationConflictError(
                "An Airflow/runtime retry is already active; wait for it to finish."
            )

        checkpoint = await self._checkpoint_for_config(config)
        if checkpoint is None:
            if latest_run is not None:
                existing_retry = await self._retry_existing_workflow(
                    latest_run,
                    latest_run_data,
                    airflow_task_state,
                    command.actor,
                )
                if existing_retry is not None:
                    return existing_retry
            result = await self._queue_new_run(
                config,
                actor=command.actor,
                message="Retry queued after a fetch failure before checkpoint creation.",
            )
            result["resumedFromUnitKey"] = None
            return result

        if self._has_live_claim(checkpoint):
            raise AutomationConflictError("Recovery is already processing a live source-unit claim.")
        status = self._status(checkpoint.status)
        if status == "BLOCKED":
            raise AutomationConflictError(
                "Checkpoint is BLOCKED and requires operator resolution before retry."
            )
        if status == "FAILED":
            if getattr(checkpoint, "retryable", None) is not True:
                raise AutomationConflictError("Checkpoint failure is terminal and cannot be retried.")
            await self._prepare_retry_if_needed(
                checkpoint,
                actor=command.actor,
                reason="Operator requested immediate recovery retry",
            )
        elif status == "DISCOVERED":
            if (getattr(checkpoint, "resolution_metadata", None) or {}).get("action") != "RETRY":
                raise AutomationConflictError(
                    "Checkpoint is waiting for review or operator resolution."
                )
        elif status != "PROCESSING":
            raise AutomationConflictError(f"Checkpoint status {status} is not recoverable.")

        if latest_run is not None:
            existing_retry = await self._retry_existing_workflow(
                latest_run,
                latest_run_data,
                airflow_task_state,
                command.actor,
            )
            if existing_retry is not None:
                existing_retry["resumedFromUnitKey"] = checkpoint.current_unit_key
                return existing_retry
        result = await self._queue_new_run(
            config,
            actor=command.actor,
            message="Recovery retry queued from checkpoint.",
        )
        result["resumedFromUnitKey"] = checkpoint.current_unit_key
        return result

    async def resolve(self, command: ResolveAutomationRecoveryCommand) -> dict[str, Any]:
        action = command.action.upper()
        reason = command.reason.strip()
        if action not in {"RETRY", "SKIP"}:
            raise AutomationValidationError("Recovery action must be RETRY or SKIP.")
        if not reason:
            raise AutomationValidationError("A reason is required for recovery resolution.")
        if len(reason) > 500:
            raise AutomationValidationError("Recovery reason must be 500 characters or fewer.")

        config = await self._config_for_partner(command.partner)
        checkpoint = await self._checkpoint_for_config(config)
        if (
            checkpoint is None
            or self._status(checkpoint.status) != "BLOCKED"
            or not getattr(checkpoint, "current_unit_key", None)
        ):
            raise AutomationConflictError(
                "Only a BLOCKED checkpoint with a current unit can be resolved."
            )

        unit_key = checkpoint.current_unit_key
        resolved = await self.checkpoint_repo.resolve_blocked(
            checkpoint,
            unit_key=unit_key,
            action=action,
            reason=reason,
            operator_id=command.actor,
        )
        if not resolved:
            raise AutomationConflictError(
                "Checkpoint changed before recovery resolution was applied."
            )
        if self.audit_recorder is not None:
            await self.audit_recorder(
                config=config,
                action=f"RECOVERY_{action}",
                actor=command.actor,
                metadata={
                    "partner": config.partner,
                    "unitKey": unit_key,
                    "reason": reason,
                    "action": action,
                },
            )
        return {
            "ok": True,
            "actor": command.actor,
            "partner": config.partner,
            "action": action,
            "unitKey": unit_key,
            "status": "DISCOVERED",
            "message": f"Recovery checkpoint resolved with action {action}.",
        }
