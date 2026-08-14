"""Shared lifecycle state and runtime boundaries for source stream runs."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.application.automation.stream_fetching import checkpoint_result
from src.domain.ingestion.checkpoints import CheckpointStatus
from src.domain.runtime.models import (
    PartnerRuntimeRunStatus,
    PartnerRuntimeTriggerType,
    RuntimeOrchestrationContext,
)


@dataclass(frozen=True)
class StreamLifecycleDependencies:
    """Runtime functions injected by the public dispatcher.

    Keeping these callables injectable preserves the existing module-level
    patch points used by scheduler and stream tests while moving lifecycle
    behavior out of ``stream_runner``.
    """

    create_runtime_run: Callable[..., Awaitable[Any]]
    update_runtime_run: Callable[..., Awaitable[Any]]
    runtime_run_repository: Any
    finish_source_stream_run: Callable[..., Awaitable[dict[str, Any]]]
    runtime_attempt_event: Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class StreamRunnerDependencies:
    """Behavioral boundaries shared by the file and paginated runners."""

    process_source_units: Any
    stage_stream_unit: Any
    evaluate_stream_mapping: Any
    create_stream_review_packet: Any
    mapping_config_repository: Any
    ingestion_error_result: Any


@dataclass
class StreamRunContext:
    """All state needed after a stream has entered the INGESTING phase."""

    config: Any
    db: Any
    config_loader: Any
    reconciliation_date: datetime
    batch_size: int
    structured_logger: Any
    mode: Any
    runtime_run_id: str | None
    mapping_config_version: str | None
    backfill_run_id: str | None
    identity: dict[str, Any]
    checkpoint_repo: Any
    checkpoint: Any
    fetcher: Any
    ingest_unit: Callable[..., Awaitable[dict[str, Any]]]
    stats: dict[str, int]
    retry_policy: Any
    raw_page_repo: Any
    stage_key: str | None
    run: Any
    cleanup_unit: Callable[..., Awaitable[None]]
    dependencies: StreamRunnerDependencies


class StreamLifecycle:
    """Own runtime creation, phase transitions, and finalization."""

    def __init__(
        self,
        *,
        db: Any,
        config: Any,
        reconciliation_date: datetime,
        runtime_run_id: str | None,
        orchestration: dict[str, Any] | None,
        dependencies: StreamLifecycleDependencies,
    ) -> None:
        self.db = db
        self.config = config
        self.reconciliation_date = reconciliation_date
        self.runtime_run_id = runtime_run_id
        self.orchestration = orchestration
        self.dependencies = dependencies
        self.run: Any = None

    async def start(self) -> Any:
        if self.runtime_run_id is None:
            self.run = await self.dependencies.create_runtime_run(
                self.db,
                partner=self.config.partner,
                date=self.reconciliation_date.strftime("%Y-%m-%d"),
                trigger_type=PartnerRuntimeTriggerType.SCHEDULER,
                triggered_by="system:scheduler",
                status=PartnerRuntimeRunStatus.FETCHING,
                message="Fetching source units sequentially.",
                orchestration=self.orchestration,
            )
            return self.run

        existing_run = await self.dependencies.runtime_run_repository(self.db).find_one(
            {"_id": self.runtime_run_id}
        )
        if existing_run is None:
            raise ValueError(f"Runtime run '{self.runtime_run_id}' was not found.")
        self.run = existing_run
        if self.orchestration is not None:
            # Build the STARTED event from the current Airflow try number.
            # The persisted runtime still contains the previous try until the
            # update below, which otherwise labels a manual retry as attempt 1.
            self.run.orchestration = RuntimeOrchestrationContext.model_validate(
                self.orchestration
            )
        await self.dependencies.update_runtime_run(
            self.db,
            str(self.run.id),
            status=PartnerRuntimeRunStatus.FETCHING,
            message="Fetching source units sequentially.",
            orchestration=self.orchestration,
            attempt_event=self.dependencies.runtime_attempt_event(
                self.run,
                "STARTED",
                message="Fetching source units sequentially.",
            ),
        )
        return self.run

    async def mark_ingesting(self) -> None:
        await self.dependencies.update_runtime_run(
            self.db,
            str(self.run.id),
            status=PartnerRuntimeRunStatus.INGESTING,
            message="Processing source units sequentially.",
        )

    async def finish(self, result: dict[str, Any], stats: dict[str, int]) -> dict[str, Any]:
        return await self.dependencies.finish_source_stream_run(
            db=self.db,
            run=self.run,
            partner=self.config.partner,
            result=result,
            stats=stats,
        )


def empty_stream_stats() -> dict[str, int]:
    """Return the unchanged stats payload used by checkpoint short-circuits."""

    return {
        "totalRows": 0,
        "successRows": 0,
        "duplicateRows": 0,
        "failedRows": 0,
        "unitsProcessed": 0,
    }


def checkpoint_short_circuit_result(checkpoint: Any) -> dict[str, Any] | None:
    """Build the legacy result for a blocked or already-ended stream."""

    if checkpoint and checkpoint.status == CheckpointStatus.BLOCKED:
        return {
            "success": False,
            "outcome": "BLOCKED",
            "processed": 0,
            "failed": 1,
            "stoppedAt": checkpoint.current_unit_key,
            "error": "Source stream is BLOCKED and requires operator resolution.",
            "errorCode": checkpoint.error_code or "checkpoint_blocked",
            "retryable": False,
            "checkpoint": checkpoint_result(checkpoint),
        }
    if checkpoint and checkpoint.stream_ended:
        return {
            "success": True,
            "processed": 0,
            "failed": 0,
            "reconciliationSkipped": True,
            "streamAlreadyCompleted": True,
            "checkpoint": checkpoint_result(checkpoint),
        }
    return None


__all__ = [
    "StreamLifecycle",
    "StreamLifecycleDependencies",
    "StreamRunContext",
    "StreamRunnerDependencies",
    "checkpoint_short_circuit_result",
    "empty_stream_stats",
]
