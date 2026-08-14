from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from src.application.reconciliation.manual_runs import (
    ManualReconciliationService,
    QueueManualReconciliationCommand,
)
from src.application.reconciliation.queries import ReconciliationRunContext
from src.application.reconciliation.queries import (
    ReconciliationContextQuery,
    ReconciliationContextUnavailableError,
)
from src.domain.runtime.models import PartnerRuntimeRunStatus


def _context() -> ReconciliationRunContext:
    return ReconciliationRunContext(
        partner="MOMO",
        date="2024-07-07",
        source_file_id="file-1",
        mapping_version="v2",
    )


def _service(*, results=None, failure=None):
    runtime_service = SimpleNamespace(
        create=AsyncMock(
            return_value=SimpleNamespace(
                id="run-1",
                partner="MOMO",
                date="2024-07-07",
                status=PartnerRuntimeRunStatus.QUEUED,
                source_file_id=None,
                mapping_version=None,
            )
        ),
        update=AsyncMock(),
    )
    reconciliation_service = SimpleNamespace(
        execute=AsyncMock(return_value=results or [])
    )
    if failure is not None:
        reconciliation_service.execute.side_effect = failure
    audit_service = SimpleNamespace(record=AsyncMock())
    context_query = SimpleNamespace(resolve=AsyncMock(return_value=_context()))
    service = ManualReconciliationService(
        runtime_service=runtime_service,
        reconciliation_service=reconciliation_service,
        audit_service=audit_service,
        context_query=context_query,
    )
    return service, runtime_service, reconciliation_service, audit_service


@pytest.mark.asyncio
async def test_queue_creates_queued_runtime_with_context() -> None:
    service, runtime_service, _, _ = _service()

    run = await service.queue(
        QueueManualReconciliationCommand(
            partner="MOMO",
            date="2024-07-07",
            triggered_by="operator",
        )
    )

    assert run.id == "run-1"
    runtime_service.create.assert_awaited_once()
    create_kwargs = runtime_service.create.await_args.kwargs
    assert create_kwargs["status"] == PartnerRuntimeRunStatus.QUEUED
    assert create_kwargs["source_file_id"] == "file-1"
    assert create_kwargs["mapping_version"] == "v2"


@pytest.mark.asyncio
async def test_execute_marks_runtime_completed_and_records_audit() -> None:
    service, runtime_service, reconciliation_service, audit_service = _service(results=[1, 2, 3])

    await service.execute("run-1", _context())

    reconciliation_service.execute.assert_awaited_once()
    runtime_service.update.assert_any_await(
        "run-1",
        status=PartnerRuntimeRunStatus.COMPLETED,
        reconciliation_count=3,
        finished_at=ANY,
        stats={"resultCount": 3},
        validation_state="NOT_RUN",
        message="Reconciliation completed successfully.",
    )
    audit_service.record.assert_awaited_once()
    assert audit_service.record.await_args.kwargs["action"] == "COMPLETED"


@pytest.mark.asyncio
async def test_execute_marks_runtime_failed_and_records_summarized_error() -> None:
    service, runtime_service, _, audit_service = _service(
        failure=RuntimeError("reconciliation exploded")
    )

    await service.execute("run-1", _context())

    failure_call = runtime_service.update.await_args_list[-1]
    assert failure_call.args[0] == "run-1"
    assert failure_call.kwargs["status"] == PartnerRuntimeRunStatus.FAILED
    assert failure_call.kwargs["message"] == "Reconciliation failed: reconciliation exploded"
    assert failure_call.kwargs["finished_at"] is not None
    audit_service.record.assert_awaited_once()
    assert audit_service.record.await_args.kwargs["action"] == "FAILED"
    assert audit_service.record.await_args.kwargs["metadata"]["error"] == (
        "reconciliation exploded"
    )


@pytest.mark.asyncio
async def test_context_query_selects_latest_runtime_source_and_mapping() -> None:
    db = MagicMock()
    post_approval = MagicMock()
    post_approval.find_one = AsyncMock(return_value=None)
    runtime = MagicMock()
    runtime.find_one = AsyncMock(
        return_value={
            "sourceFileId": "file-2",
            "mappingVersion": "v3",
            "createdAt": datetime(2024, 7, 7, 3, tzinfo=UTC),
        }
    )
    reconciliation_file = MagicMock()
    reconciliation_file.find_one = AsyncMock(return_value=None)
    collections = {
        "post_approval_run": post_approval,
        "partner_runtime_run": runtime,
        "reconciliation_file": reconciliation_file,
    }
    db.__getitem__.side_effect = collections.__getitem__
    query = ReconciliationContextQuery(
        db,
        row_counter=AsyncMock(return_value=4),
    )

    context = await query.resolve("MOMO", "2024-07-07")

    assert context == ReconciliationRunContext(
        partner="MOMO",
        date="2024-07-07",
        source_file_id="file-2",
        mapping_version="v3",
    )


@pytest.mark.asyncio
async def test_context_query_rejects_missing_ingested_source() -> None:
    db = MagicMock()
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=None)
    db.__getitem__.return_value = collection
    query = ReconciliationContextQuery(
        db,
        row_counter=AsyncMock(return_value=0),
    )

    with pytest.raises(ReconciliationContextUnavailableError, match="No partner file context"):
        await query.resolve("MOMO", "2024-07-07")
