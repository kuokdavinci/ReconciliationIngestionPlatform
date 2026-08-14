"""Architecture checks for the runtime visibility bounded context."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.runtime.models import (
    PartnerRuntimeRun,
    PartnerRuntimeRunStatus,
    PartnerRuntimeTriggerType,
    RuntimeOrchestrationContext,
)
from src.infrastructure.runtime.repository import PartnerRuntimeRunRepository
from src.models.partner_runtime_run import (
    PartnerRuntimeRun as LegacyPartnerRuntimeRun,
    PartnerRuntimeRunRepository as LegacyPartnerRuntimeRunRepository,
    PartnerRuntimeRunStatus as LegacyPartnerRuntimeRunStatus,
    PartnerRuntimeTriggerType as LegacyPartnerRuntimeTriggerType,
)
from src.application.runtime.service import serialize_partner_runtime_run, update_runtime_run


def test_legacy_runtime_module_is_a_compatibility_facade() -> None:
    """Legacy imports must resolve to domain and infrastructure implementations."""

    assert LegacyPartnerRuntimeRun is PartnerRuntimeRun
    assert LegacyPartnerRuntimeRunRepository is PartnerRuntimeRunRepository
    assert LegacyPartnerRuntimeRunStatus is PartnerRuntimeRunStatus
    assert LegacyPartnerRuntimeTriggerType is PartnerRuntimeTriggerType


def test_runtime_run_serializes_airflow_correlation() -> None:
    run = PartnerRuntimeRun(
        partner="VIETTELPAY",
        date="2026-08-09",
        triggerType=PartnerRuntimeTriggerType.SCHEDULER,
        orchestration=RuntimeOrchestrationContext(
            dagId="reconciliation_ingestion",
            dagRunId="scheduled__2026-08-09",
            taskId="run_stream",
            mapIndex=0,
            tryNumber=2,
            logicalDate=datetime(2026, 8, 8, 17, 0, tzinfo=UTC),
            correlationId="correlation-1",
        ),
    )

    serialized = serialize_partner_runtime_run(run)

    assert serialized["orchestration"] == {
        "provider": "AIRFLOW",
        "dagId": "reconciliation_ingestion",
        "dagRunId": "scheduled__2026-08-09",
        "taskId": "run_stream",
        "mapIndex": 0,
        "tryNumber": 2,
        "logicalDate": "2026-08-08T17:00:00+00:00",
        "correlationId": "correlation-1",
    }


@pytest.mark.asyncio
async def test_update_runtime_run_persists_orchestration_context() -> None:
    collection = MagicMock()
    collection.update_one = AsyncMock()
    db = MagicMock()
    db.__getitem__.return_value = collection
    orchestration = RuntimeOrchestrationContext(
        dagId="reconciliation_ingestion",
        dagRunId="manual__runtime-1",
        taskId="run_stream",
    )

    await update_runtime_run(
        db,
        "runtime-1",
        orchestration=orchestration,
    )

    update = collection.update_one.await_args.args[1]["$set"]
    assert update["orchestration"]["dagRunId"] == "manual__runtime-1"


@pytest.mark.asyncio
async def test_update_runtime_run_appends_attempt_history_without_overwriting_it() -> None:
    collection = MagicMock()
    collection.update_one = AsyncMock()
    db = MagicMock()
    db.__getitem__.return_value = collection

    await update_runtime_run(
        db,
        "runtime-1",
        attempt_event={
            "eventId": "attempt-1",
            "status": "FAILED",
            "timestamp": "2026-08-10T00:00:01+00:00",
        },
    )

    update = collection.update_one.await_args.args[1]
    assert update["$push"]["attemptHistory"]["eventId"] == "attempt-1"


@pytest.mark.asyncio
async def test_update_runtime_run_can_clear_terminal_timestamp_for_in_place_retry() -> None:
    collection = MagicMock()
    collection.update_one = AsyncMock()
    db = MagicMock()
    db.__getitem__.return_value = collection

    await update_runtime_run(db, "runtime-1", clear_finished_at=True)

    update = collection.update_one.await_args.args[1]["$set"]
    assert update["finishedAt"] is None
