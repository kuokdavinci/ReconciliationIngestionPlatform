"""TDD contracts for source-unit quarantine blocker policy."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.ingestion.quarantine import (
    IngestionQuarantineRecord,
    QuarantinePhase,
    QuarantineStatus,
)


def _record(
    *,
    source_unit_key: str = "unit-1",
    status: QuarantineStatus = QuarantineStatus.PENDING,
    error_code: str = "CONFLICTING_DUPLICATE",
) -> IngestionQuarantineRecord:
    return IngestionQuarantineRecord(
        sourceFileId="file-1",
        sourceUnitKey=source_unit_key,
        partner="MOMO",
        reconciliationDate=datetime(2026, 8, 1, tzinfo=UTC),
        rowNumber=7,
        rawRow=("TX-007", "100"),
        phase=QuarantinePhase.BATCH,
        status=status,
        errors=[{"errorCode": error_code}],
    )


def _repo(active, all_records=None):
    repository = MagicMock()
    repository.find_blockers = AsyncMock(return_value=active)
    repository.find_many = AsyncMock(
        return_value=(all_records if all_records is not None else active, None)
    )
    return repository


@pytest.mark.asyncio
async def test_no_blockers_is_ready_to_resume():
    from src.application.ingestion.quarantine_source_unit import (
        resolve_quarantine_source_unit,
    )

    result = await resolve_quarantine_source_unit(
        "unit-1", "operator-1", "reviewed"
    )

    assert result.source_unit_key == "unit-1"
    assert result.blocker_count == 0
    assert result.resolved_count == 0
    assert result.ready_to_resume is True


@pytest.mark.asyncio
async def test_pending_conflicting_duplicate_holds_source_unit():
    from src.application.ingestion.quarantine_source_unit import (
        resolve_quarantine_source_unit,
    )

    record = _record()
    result = await resolve_quarantine_source_unit(
        "unit-1", "operator-1", "waiting for source correction", _repo([record])
    )

    assert result.blocker_count == 1
    assert result.ready_to_resume is False
    assert result.reason == "UNRESOLVED_CONFLICTING_DUPLICATE"


@pytest.mark.asyncio
async def test_resolved_conflict_and_pending_ordinary_reject_are_resume_ready():
    from src.application.ingestion.quarantine_source_unit import (
        resolve_quarantine_source_unit,
    )

    resolved_conflict = _record(status=QuarantineStatus.RESOLVED)
    pending_reject = _record(error_code="INVALID_AMOUNT")
    result = await resolve_quarantine_source_unit(
        "unit-1",
        "operator-1",
        "conflict accepted",
        _repo([pending_reject], [resolved_conflict, pending_reject]),
    )

    assert result.blocker_count == 0
    assert result.resolved_count == 1
    assert result.ready_to_resume is True
    assert result.reason == "READY_AFTER_CONFLICT_RESOLUTION"


@pytest.mark.asyncio
async def test_mixed_source_units_only_evaluates_requested_unit():
    from src.application.ingestion.quarantine_source_unit import (
        resolve_quarantine_source_unit,
    )

    repository = _repo([_record(source_unit_key="unit-2")])
    result = await resolve_quarantine_source_unit(
        "unit-1", "operator-1", "reviewed", repository
    )

    assert result.blocker_count == 0
    assert result.ready_to_resume is True
    repository.find_blockers.assert_awaited_once_with("unit-1")


@pytest.mark.asyncio
async def test_repository_blocker_queries_use_active_status_and_conflict_code():
    from src.infrastructure.ingestion.quarantine_repository import (
        IngestionQuarantineRepository,
    )

    collection = MagicMock()
    collection.find_one = AsyncMock()
    collection.find.return_value = _AsyncCursor([])
    collection.find_one.return_value = {"_id": "record-1"}
    db = MagicMock()
    db.__getitem__.return_value = collection
    repository = IngestionQuarantineRepository(db)

    assert await repository.find_blockers("unit-1") == []
    assert await repository.has_unresolved_blockers("unit-1") is True

    blocker_query = collection.find.call_args.args[0]
    assert blocker_query["sourceUnitKey"] == "unit-1"
    assert blocker_query["status"]["$in"] == ["PENDING", "REPROCESSING"]
    conflict_query = collection.find_one.call_args.args[0]
    assert conflict_query["errors.errorCode"] == "CONFLICTING_DUPLICATE"


class _AsyncCursor:
    def __init__(self, values):
        self.values = iter(values)

    def sort(self, *_args, **_kwargs):
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.values)
        except StopIteration as exc:
            raise StopAsyncIteration from exc
