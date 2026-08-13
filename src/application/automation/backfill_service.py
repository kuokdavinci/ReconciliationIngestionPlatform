"""Application orchestration service for durable parent backfill runs."""

from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from typing import Any, Optional

from src.application.automation.contracts import ExecuteStreamCommand
from src.application.automation.workflows import (
    WorkflowSubmissionConflict,
    WorkflowUnavailable,
)
from src.domain.backfill.models import (
    BackfillApprovalContext,
    BackfillDayStatus,
    BackfillDayRecord,
    BackfillRun,
    BackfillRunStatus,
)
from src.domain.ingestion.checkpoints import IngestionMode
from src.domain.runtime.models import RuntimeOrchestrationContext


class BackfillRunError(Exception):
    """Base error for backfill application failures."""


class BackfillRunValidationError(BackfillRunError):
    """The requested backfill input is invalid."""


class BackfillRunNotFoundError(BackfillRunError):
    """A required backfill or fetch configuration does not exist."""


class BackfillRunConflictError(BackfillRunError):
    """The requested backfill conflicts with an active workflow."""


class BackfillRunUnavailableError(BackfillRunError):
    """The workflow provider cannot accept the backfill."""


def expand_business_dates(from_date: date, to_date: date) -> list[date]:
    if from_date > to_date:
        raise BackfillRunValidationError("fromDate must be on or before toDate.")

    values: list[date] = []
    cursor = from_date
    while cursor <= to_date:
        if cursor.weekday() < 5:
            values.append(cursor)
        cursor += timedelta(days=1)

    if not values:
        raise BackfillRunValidationError("Backfill range must include at least one business day.")
    if len(values) > 31:
        raise BackfillRunValidationError("Backfill range cannot exceed 31 business days.")
    return values


def serialize_backfill_run(run: BackfillRun) -> dict[str, Any]:
    payload = run.model_dump(by_alias=True, mode="json")
    payload["_id"] = str(payload["_id"])
    return payload


class BackfillRunService:
    def __init__(
        self,
        *,
        fetch_repo,
        backfill_repo,
        workflow_gateway,
        approved_mapping_version_finder: Callable[[str], Awaitable[str | None]],
        pending_review_packet_finder: Callable[[str, str], Awaitable[str | None]] | None = None,
    ) -> None:
        self._fetch_repo = fetch_repo
        self._backfill_repo = backfill_repo
        self._workflow_gateway = workflow_gateway
        self._approved_mapping_version_finder = approved_mapping_version_finder
        self._pending_review_packet_finder = pending_review_packet_finder

    async def start(
        self,
        *,
        partner: str,
        actor: str,
        from_date: date,
        to_date: date,
        fetch_config_id: Optional[str] = None,
    ) -> BackfillRun:
        business_dates = expand_business_dates(from_date, to_date)
        config = (
            await self._fetch_repo.find_by_id(fetch_config_id)
            if fetch_config_id
            else await self._fetch_repo.find_by_partner(partner)
        )
        if config is None or config.partner != partner:
            raise BackfillRunNotFoundError("Automation job not found for partner.")
        if not config.enabled:
            raise BackfillRunValidationError("Automation job is disabled.")

        existing_run_finder = getattr(self._backfill_repo, "find_latest_active_by_partner", None)
        existing_run = (
            await existing_run_finder(partner)
            if existing_run_finder is not None
            else None
        )
        if existing_run is not None:
            if existing_run.from_date == from_date and existing_run.to_date == to_date:
                return existing_run
            status = getattr(existing_run.status, "value", existing_run.status)
            checkpoint = (
                existing_run.current_date.isoformat()
                if existing_run.current_date
                else "the current checkpoint"
            )
            raise BackfillRunConflictError(
                f"An active backfill is already {status} at {checkpoint}; resume that run instead of creating another."
            )

        mapping_version = await self._approved_mapping_version_finder(partner)
        approval_required = mapping_version is None
        run = BackfillRun(
            partner=partner,
            fetchConfigId=str(config.id),
            status=(
                BackfillRunStatus.WAITING_CONFIG
                if approval_required
                else BackfillRunStatus.QUEUED
            ),
            fromDate=from_date,
            toDate=to_date,
            currentDate=business_dates[0],
            completedDays=0,
            totalDays=len(business_dates),
            configVersion=str(config.updated_at),
            mappingVersion=mapping_version,
            approvalRequired=approval_required,
            approvalContext=(
                BackfillApprovalContext(
                    workflowType="UPC",
                    fileType="SETTLEMENT",
                )
                if approval_required
                else None
            ),
            triggeredBy=actor,
            days=[BackfillDayRecord(businessDate=value) for value in business_dates],
        )
        await self._backfill_repo.create(run)
        if approval_required:
            if self._pending_review_packet_finder is not None:
                packet_id = await self._pending_review_packet_finder(partner, str(run.id))
                if packet_id:
                    run.approval_context = BackfillApprovalContext(
                        workflowType="UPC",
                        fileType="SETTLEMENT",
                        reviewPacketId=packet_id,
                    )
                    await self._backfill_repo.update_status(
                        str(run.id),
                        approvalContext=run.approval_context.model_dump(
                            by_alias=True,
                            mode="json",
                        ),
                    )
            return run

        command = self._command_for_run(
            run=run,
            fetchConfigId=str(config.id),
            partner=partner,
            configVersion=str(config.updated_at),
        )
        try:
            submission = await self._workflow_gateway.trigger(command)
        except WorkflowSubmissionConflict as exc:
            await self._backfill_repo.update_status(
                str(run.id),
                status=BackfillRunStatus.FAILED.value,
            )
            raise BackfillRunConflictError("Workflow run ID collision.") from exc
        except WorkflowUnavailable as exc:
            await self._backfill_repo.update_status(
                str(run.id),
                status=BackfillRunStatus.FAILED.value,
            )
            raise BackfillRunUnavailableError("Workflow orchestration is unavailable.") from exc

        run.orchestration = RuntimeOrchestrationContext(
            dagId=submission.workflow_id,
            dagRunId=submission.workflow_run_id,
            taskId="run_stream",
            correlationId=command.correlation_id,
        )
        await self._backfill_repo.update_status(
            str(run.id),
            orchestration=run.orchestration.model_dump(by_alias=True, mode="json"),
        )
        return run

    async def resume_after_approval(
        self,
        *,
        backfill_run_id: str,
        mapping_version: str,
    ) -> BackfillRun:
        run = await self.get(backfill_run_id)
        stale_queued_checkpoint = self._is_stale_queued_checkpoint(run)
        if run.status != BackfillRunStatus.WAITING_CONFIG and not stale_queued_checkpoint:
            raise BackfillRunConflictError("Backfill is not waiting for mapping approval.")
        config = await self._fetch_repo.find_by_id(run.fetch_config_id)
        if config is None or config.partner != run.partner or not config.enabled:
            raise BackfillRunNotFoundError("Backfill fetch configuration is no longer available.")

        command = self._command_for_run(
            run=run,
            fetchConfigId=str(config.id),
            partner=run.partner,
            configVersion=str(config.updated_at),
            mappingVersion=mapping_version,
        )
        if stale_queued_checkpoint:
            submission = await self._retry_stale_queued_checkpoint(run)
        else:
            try:
                submission = await self._workflow_gateway.trigger(command)
            except WorkflowSubmissionConflict as exc:
                raise BackfillRunConflictError("Workflow run ID collision.") from exc
            except WorkflowUnavailable as exc:
                raise BackfillRunUnavailableError("Workflow orchestration is unavailable.") from exc

        orchestration = RuntimeOrchestrationContext(
            dagId=submission.workflow_id,
            dagRunId=submission.workflow_run_id,
            taskId="run_stream",
            correlationId=command.correlation_id,
        )
        await self._backfill_repo.update_status(
            backfill_run_id,
            status=BackfillRunStatus.QUEUED.value,
            approvalRequired=False,
            configVersion=str(config.updated_at),
            mappingVersion=mapping_version,
            orchestration=orchestration.model_dump(by_alias=True, mode="json"),
        )
        run.status = BackfillRunStatus.QUEUED
        run.approval_required = False
        run.config_version = str(config.updated_at)
        run.mapping_version = mapping_version
        run.orchestration = orchestration
        return run

    @staticmethod
    def _is_stale_queued_checkpoint(run: BackfillRun) -> bool:
        if run.status != BackfillRunStatus.QUEUED or run.orchestration is None:
            return False
        current_date = run.current_date
        return any(
            day.status == BackfillDayStatus.WAITING_CONFIG
            and (current_date is None or day.business_date == current_date)
            for day in run.days
        )

    async def _retry_stale_queued_checkpoint(self, run: BackfillRun):
        orchestration = run.orchestration
        task_state_reader = getattr(self._workflow_gateway, "task_state", None)
        task_retrier = getattr(self._workflow_gateway, "retry_task", None)
        if orchestration is None or not callable(task_state_reader) or not callable(task_retrier):
            raise BackfillRunUnavailableError(
                "The existing backfill checkpoint cannot be recovered by its workflow provider."
            )

        task_id = orchestration.task_id or "run_stream"
        map_index = orchestration.map_index if orchestration.map_index is not None else 0
        try:
            task_state = await task_state_reader(
                orchestration.dag_run_id,
                task_id=task_id,
                map_index=map_index,
            )
        except Exception as exc:
            raise BackfillRunUnavailableError(
                "Unable to inspect the existing backfill workflow."
            ) from exc

        if str(task_state or "").lower() not in {
            "success",
            "failed",
            "upstream_failed",
            "up_for_retry",
        }:
            raise BackfillRunConflictError(
                "The existing backfill workflow is still active; wait for it before resuming."
            )
        try:
            return await task_retrier(
                orchestration.dag_run_id,
                task_id=task_id,
                map_index=map_index,
            )
        except WorkflowSubmissionConflict as exc:
            raise BackfillRunConflictError("Workflow run ID collision.") from exc
        except Exception as exc:
            raise BackfillRunUnavailableError(
                "The existing backfill workflow could not be retried."
            ) from exc

    @staticmethod
    def _command_for_run(*, run: BackfillRun, **values: Any) -> ExecuteStreamCommand:
        mapping_version = values.pop("mappingVersion", run.mapping_version)
        return ExecuteStreamCommand(
            **values,
            mode=IngestionMode.BACKFILL,
            runtimeRunId=str(run.id),
            correlationId=f"backfill:{run.id}",
            mappingVersion=mapping_version,
            backfillRunId=str(run.id),
            fromDate=run.from_date,
            toDate=run.to_date,
        )

    async def get(self, backfill_run_id: str) -> BackfillRun:
        run = await self._backfill_repo.find_by_id(backfill_run_id)
        if run is None:
            raise BackfillRunNotFoundError("Backfill run not found.")
        return run
