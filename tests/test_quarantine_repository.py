from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.ingestion.quarantine import (
    IngestionQuarantineRecord,
    QuarantineAction,
    QuarantinePhase,
    QuarantineStatus,
)
from src.infrastructure.ingestion.quarantine_repository import (
    IngestionQuarantineRepository,
)


def _record(status: QuarantineStatus = QuarantineStatus.PENDING):
    record = IngestionQuarantineRecord(
        sourceFileId="file-1",
        sourceUnitKey="unit-1",
        partner="MOMO",
        reconciliationDate=datetime(2026, 8, 26, tzinfo=UTC),
        rowNumber=2,
        rawRow=["tx-1", "10.00"],
        errors=[{"errorCode": "INVALID_AMOUNT"}],
        status=status,
    )
    raw = record.model_dump(by_alias=True)
    raw["_id"] = str(record.id)
    return record, raw


def _repository():
    collection = MagicMock()
    database = MagicMock()
    database.__getitem__.return_value = collection
    return IngestionQuarantineRepository(database), collection


class _AsyncCursor:
    def __init__(self, records):
        self.records = records
        self.sort_args = None
        self.limit_value = None

    def sort(self, fields):
        self.sort_args = fields
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.records:
            raise StopAsyncIteration
        return self.records.pop(0)


@pytest.mark.asyncio
async def test_claim_atomically_moves_pending_record_to_reprocessing():
    record, pending = _record()
    _, reprocessing = _record(QuarantineStatus.REPROCESSING)
    reprocessing["_id"] = str(record.id)
    reprocessing["claimedBy"] = "operator-1"
    reprocessing["attemptCount"] = 2
    repository, collection = _repository()
    collection.find_one = AsyncMock(return_value=pending)
    collection.find_one_and_update = AsyncMock(return_value=reprocessing)

    claim = getattr(repository, "claim", None)
    assert claim is not None
    result = await claim(str(record.id), "operator-1", lease_seconds=120)

    assert result is not None
    assert result.status is QuarantineStatus.REPROCESSING
    assert result.claimed_by == "operator-1"
    query, update = collection.find_one_and_update.call_args.args[:2]
    assert query["_id"] == str(record.id)
    assert query["status"] == QuarantineStatus.PENDING.value
    assert update["$set"]["status"] == QuarantineStatus.REPROCESSING.value
    assert update["$set"]["claimExpiresAt"] is not None
    assert update["$inc"] == {"attemptCount": 1}


@pytest.mark.asyncio
async def test_second_claim_returns_none_when_atomic_update_loses():
    record, pending = _record()
    repository, collection = _repository()
    collection.find_one = AsyncMock(return_value=pending)
    collection.find_one_and_update = AsyncMock(return_value=None)

    claim = getattr(repository, "claim", None)
    assert claim is not None
    result = await claim(str(record.id), "operator-2", lease_seconds=120)

    assert result is None


@pytest.mark.asyncio
async def test_resolve_requires_reprocessing_and_operator_claim():
    record, reprocessing = _record(QuarantineStatus.REPROCESSING)
    reprocessing["_id"] = str(record.id)
    reprocessing["claimedBy"] = "operator-1"
    repository, collection = _repository()
    collection.find_one = AsyncMock(return_value=reprocessing)
    collection.update_one = AsyncMock(
        return_value=SimpleNamespace(modified_count=1)
    )

    resolve = getattr(repository, "resolve", None)
    assert resolve is not None
    resolved = await resolve(
        str(record.id),
        QuarantineStatus.RESOLVED,
        "operator-1",
        QuarantineAction.REPROCESS,
        "Corrected amount persisted.",
        {"source": "test"},
    )

    assert resolved is True
    query, update = collection.update_one.call_args.args
    assert query["status"] == QuarantineStatus.REPROCESSING.value
    assert query["claimedBy"] == "operator-1"
    assert update["$set"]["status"] == QuarantineStatus.RESOLVED.value
    assert update["$push"]["resolutionHistory"]["action"] == "REPROCESS"


@pytest.mark.asyncio
async def test_release_for_retry_clears_claim_and_records_reason():
    record, reprocessing = _record(QuarantineStatus.REPROCESSING)
    reprocessing["_id"] = str(record.id)
    reprocessing["claimedBy"] = "operator-1"
    repository, collection = _repository()
    collection.find_one = AsyncMock(return_value=reprocessing)
    collection.update_one = AsyncMock(
        return_value=SimpleNamespace(modified_count=1)
    )

    release = getattr(repository, "release_for_retry", None)
    assert release is not None
    released = await release(
        str(record.id),
        "operator-1",
        "Transient database timeout.",
        {"retryable": True},
    )

    assert released is True
    _, update = collection.update_one.call_args.args
    assert update["$set"]["status"] == QuarantineStatus.PENDING.value
    assert update["$set"]["claimedBy"] is None
    assert update["$set"]["lastAttemptError"] == "Transient database timeout."


@pytest.mark.asyncio
async def test_resolve_rejects_invalid_target_before_database_update():
    record, reprocessing = _record(QuarantineStatus.REPROCESSING)
    reprocessing["_id"] = str(record.id)
    reprocessing["claimedBy"] = "operator-1"
    repository, collection = _repository()
    collection.find_one = AsyncMock(return_value=reprocessing)
    collection.update_one = AsyncMock(
        return_value=SimpleNamespace(modified_count=1)
    )

    resolve = getattr(repository, "resolve", None)
    assert resolve is not None
    with pytest.raises(ValueError):
        await resolve(
            str(record.id),
            QuarantineStatus.REPROCESSING,
            "operator-1",
            QuarantineAction.REPROCESS,
            "Invalid target.",
        )

    collection.update_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_find_many_builds_structured_filters_and_stable_cursor():
    query_model = getattr(__import__("src.domain.ingestion.quarantine", fromlist=["QuarantineQuery"]), "QuarantineQuery", None)
    assert query_model is not None

    first, first_raw = _record()
    first_raw["_id"] = str(first.id)
    first_raw["createdAt"] = datetime(2026, 8, 25, tzinfo=UTC)
    second, second_raw = _record()
    second_raw["_id"] = str(second.id)
    second_raw["createdAt"] = datetime(2026, 8, 26, tzinfo=UTC)
    cursor = _AsyncCursor([first_raw, second_raw])
    repository, collection = _repository()
    collection.find.return_value = cursor

    find_many = getattr(repository, "find_many", None)
    assert find_many is not None
    records, next_cursor = await find_many(
        query_model(
            partner="MOMO",
            status=QuarantineStatus.PENDING,
            phase=QuarantinePhase.VALIDATION,
            error_code="INVALID_AMOUNT",
            sourceFileId="file-1",
            sourceUnitKey="unit-1",
            fromDate=datetime(2026, 8, 1, tzinfo=UTC),
            toDate=datetime(2026, 9, 1, tzinfo=UTC),
            limit=2,
        )
    )

    query = collection.find.call_args.args[0]
    assert query["partner"] == "MOMO"
    assert query["status"] == "PENDING"
    assert query["phase"] == "VALIDATION"
    assert query["errors.errorCode"] == "INVALID_AMOUNT"
    assert query["sourceFileId"] == "file-1"
    assert query["sourceUnitKey"] == "unit-1"
    assert query["createdAt"]["$gte"] == datetime(2026, 8, 1, tzinfo=UTC)
    assert query["createdAt"]["$lt"] == datetime(2026, 9, 1, tzinfo=UTC)
    assert cursor.sort_args == [("createdAt", 1), ("_id", 1)]
    assert cursor.limit_value == 2
    assert len(records) == 2
    assert next_cursor is not None
