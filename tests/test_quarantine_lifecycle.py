from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from src.config.settings import settings
from src.domain.ingestion.quarantine import (
    IngestionQuarantineRecord,
    QuarantineStatus,
    QuarantineTransitionStatus,
)
from src.infrastructure.ingestion.quarantine_repository import (
    IngestionQuarantineRepository,
)
from src.infrastructure.persistence.mongo_indexes import INDEXES


def _record(**updates) -> IngestionQuarantineRecord:
    values = {
        "source_file_id": "file-1",
        "partner": "MOMO",
        "reconciliation_date": datetime(2026, 1, 1, tzinfo=UTC),
        "raw_row": {"amount": "bad"},
    }
    values.update(updates)
    return IngestionQuarantineRecord(**values)


class _AsyncCursor:
    def __init__(self, records):
        self.records = records
        self.limit_values = []

    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, _limit):
        self.limit_values.append(_limit)
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.records:
            raise StopAsyncIteration
        return self.records.pop(0).model_dump(by_alias=True)


def _repository(records=None):
    collection = MagicMock()
    cursor = _AsyncCursor(records or [])
    collection.find = MagicMock(return_value=cursor)
    collection.cursor = cursor
    collection.find_one = AsyncMock(return_value=None)
    collection.update_one = AsyncMock(return_value=SimpleNamespace(modified_count=1))
    collection.find_one_and_update = AsyncMock(return_value=None)
    collection.insert_many = AsyncMock()
    repository = IngestionQuarantineRepository(MagicMock())
    repository.collection = collection
    return repository, collection


def test_quarantine_record_has_bounded_lifecycle_fields():
    record = _record()

    assert record.expires_at is None
    assert record.claimed_by is None
    assert record.claimed_at is None
    assert record.last_action_id is None


@pytest.mark.asyncio
async def test_create_many_applies_configured_expiry_without_raw_metadata():
    repository, collection = _repository()
    records = [_record()]
    previous = settings.ingestion_quarantine_retention_days
    settings.ingestion_quarantine_retention_days = 30
    try:
        created = await repository.create_many(records)
    finally:
        settings.ingestion_quarantine_retention_days = previous

    assert created == 1
    inserted = collection.insert_many.await_args.args[0][0]
    expiry = inserted["expiresAt"]
    assert datetime.now(UTC) + timedelta(days=29) < expiry
    assert expiry < datetime.now(UTC) + timedelta(days=31)


@pytest.mark.asyncio
async def test_list_records_filters_partner_and_status_in_created_order():
    records = [
        _record(id=UUID("00000000-0000-0000-0000-000000000001"), status=QuarantineStatus.PENDING),
        _record(id=UUID("00000000-0000-0000-0000-000000000002"), status=QuarantineStatus.PENDING),
    ]
    repository, collection = _repository(records)

    result = await repository.list_records(partner="MOMO", status=QuarantineStatus.PENDING, limit=2)

    assert [item.id for item in result] == [
        UUID("00000000-0000-0000-0000-000000000001"),
        UUID("00000000-0000-0000-0000-000000000002"),
    ]
    collection.find.assert_called_once_with(
        {"partner": "MOMO", "status": QuarantineStatus.PENDING.value}
    )


@pytest.mark.asyncio
async def test_transition_uses_expected_status_and_action_id_cas():
    repository, collection = _repository()
    applied = _record(id=UUID("00000000-0000-0000-0000-000000000005"))
    collection.find_one_and_update = AsyncMock(
        return_value=applied.model_dump(by_alias=True)
    )

    result = await repository.transition(
        "record-1",
        expected_status=QuarantineStatus.PENDING,
        new_status=QuarantineStatus.REPROCESSING,
        metadata={"actor": "operator-1"},
        action_id="action-1",
    )

    assert result.status is QuarantineTransitionStatus.APPLIED
    query = collection.find_one_and_update.await_args.args[0]
    assert query == {
        "_id": "record-1",
        "status": QuarantineStatus.PENDING.value,
        "lastActionId": {"$ne": "action-1"},
    }


@pytest.mark.asyncio
async def test_transition_replays_same_action_without_second_update():
    repository, collection = _repository()
    existing = _record(
        id=UUID("00000000-0000-0000-0000-000000000003"),
        last_action_id="action-1",
    )
    collection.find_one_and_update = AsyncMock(return_value=None)
    collection.find_one = AsyncMock(return_value=existing.model_dump(by_alias=True))

    result = await repository.transition(
        "record-1",
        expected_status=QuarantineStatus.PENDING,
        new_status=QuarantineStatus.REPROCESSING,
        metadata={"actor": "operator-1"},
        action_id="action-1",
    )

    assert result.status is QuarantineTransitionStatus.REPLAYED
    assert result.record is not None


@pytest.mark.asyncio
async def test_transition_reports_conflict_when_status_changed():
    repository, collection = _repository()
    existing = _record(
        id=UUID("00000000-0000-0000-0000-000000000004"),
        status=QuarantineStatus.REJECTED,
    )
    collection.find_one_and_update = AsyncMock(return_value=None)
    collection.find_one = AsyncMock(return_value=existing.model_dump(by_alias=True))

    result = await repository.transition(
        "record-1",
        expected_status=QuarantineStatus.PENDING,
        new_status=QuarantineStatus.REPROCESSING,
        metadata={"actor": "operator-1"},
        action_id="action-2",
    )

    assert result.status is QuarantineTransitionStatus.CONFLICT


def test_quarantine_ttl_index_is_explicit_and_non_transactional():
    indexes = INDEXES["ingestion_quarantine_record"]

    ttl = next(index for index in indexes if index.document["name"] == "idx_quarantine_expires_at_ttl")

    assert ttl.document["expireAfterSeconds"] == 0
    assert ttl.document["key"] == {"expiresAt": 1}


@pytest.mark.asyncio
async def test_mark_status_sanitizes_legacy_metadata():
    repository, collection = _repository()

    await repository.mark_status(
        "record-1",
        QuarantineStatus.REJECTED,
        metadata={
            "rawRow": {"amount": "10"},
            "incomingFingerprint": "fingerprint",
            "exception": "full exception payload",
            "token": "secret",
            "errorMessage": "full error payload",
            "stackTrace": "full stack payload",
            "apiKey": "secret key",
            "authorization": "Bearer secret",
            "reason": "manual disposition",
        },
    )

    update = collection.update_one.await_args.args[1]["$set"]
    assert update["resolutionMetadata"] == {"reason": "manual disposition"}


@pytest.mark.asyncio
async def test_list_records_clamps_non_positive_and_large_limits():
    repository, collection = _repository()

    await repository.list_records(limit=0)
    await repository.list_records(limit=-5)
    await repository.list_records(limit=999999)

    assert collection.cursor.limit_values == [1, 1, 200]


@pytest.mark.asyncio
async def test_create_many_never_extends_explicit_expiry_beyond_policy():
    repository, collection = _repository()
    records = [_record(expires_at=datetime.now(UTC) + timedelta(days=365))]

    await repository.create_many(records)

    inserted_expiry = collection.insert_many.await_args.args[0][0]["expiresAt"]
    assert inserted_expiry < datetime.now(UTC) + timedelta(days=31)


@pytest.mark.asyncio
async def test_transition_rejects_unbounded_action_id():
    repository, _collection = _repository()

    with pytest.raises(ValueError, match="action_id"):
        await repository.transition(
            "record-1",
            expected_status=QuarantineStatus.PENDING,
            new_status=QuarantineStatus.REPROCESSING,
            action_id="x" * 129,
        )
