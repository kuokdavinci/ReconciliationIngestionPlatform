"""TDD contracts for bounded quarantine retention cleanup."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.ingestion.quarantine import QuarantineStatus


def _cursor(documents):
    return _AsyncCursor(documents)


class _AsyncCursor:
    def __init__(self, documents):
        self.documents = iter(documents)
        self.limit_value = None

    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.documents)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


def _repo(cursor):
    collection = MagicMock()
    collection.find.return_value = cursor
    collection.delete_one = AsyncMock(
        side_effect=lambda _query: MagicMock(deleted_count=1)
    )
    db = MagicMock()
    db.__getitem__.return_value = collection
    from src.infrastructure.ingestion.quarantine_repository import (
        IngestionQuarantineRepository,
    )

    return IngestionQuarantineRepository(db), collection


def test_retention_policy_has_explicit_terminal_and_payload_windows():
    from src.domain.ingestion.quarantine import QuarantineRetentionPolicy

    policy = QuarantineRetentionPolicy(
        resolvedDays=30,
        rejectedDays=90,
        sanitizedRowDays=7,
    )

    assert policy.days_for(QuarantineStatus.RESOLVED) == 30
    assert policy.days_for(QuarantineStatus.REJECTED) == 90
    assert policy.sanitized_row_days == 7


@pytest.mark.asyncio
async def test_purge_query_is_terminal_and_bounded():
    now = datetime(2026, 8, 26, tzinfo=UTC)
    cursor = _cursor([{"_id": "record-1"}, {"_id": "record-2"}])
    repository, collection = _repo(cursor)

    removed = await repository.purge_expired(now, limit=2)

    assert removed == 2
    query = collection.find.call_args.args[0]
    assert query["status"]["$in"] == ["RESOLVED", "REJECTED"]
    assert query["retentionUntil"]["$lte"] == now
    assert cursor.limit_value == 2
    assert collection.delete_one.await_count == 2


@pytest.mark.asyncio
async def test_purge_does_not_delete_when_no_terminal_record_is_expired():
    cursor = _cursor([])
    repository, collection = _repo(cursor)

    removed = await repository.purge_expired(
        datetime.now(UTC),
        limit=100,
    )

    assert removed == 0
    collection.delete_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_purge_rejects_invalid_limit():
    repository, _collection = _repo(_cursor([]))

    with pytest.raises(ValueError, match="limit"):
        await repository.purge_expired(datetime.now(UTC), limit=0)


@pytest.mark.asyncio
async def test_resolve_applies_terminal_retention_until():
    from src.domain.ingestion.quarantine import QuarantineAction, QuarantineRetentionPolicy

    policy = QuarantineRetentionPolicy(resolvedDays=30, rejectedDays=90)
    repository, collection = _repo(_cursor([]))
    repository.retention_policy = policy
    repository.find_by_id = AsyncMock(
        return_value=MagicMock(
            status=QuarantineStatus.REPROCESSING,
            claimed_by="operator-1",
            attempt_count=2,
        )
    )
    collection.update_one = AsyncMock(return_value=MagicMock(modified_count=1))

    assert await repository.resolve(
        "record-1",
        QuarantineStatus.RESOLVED,
        "operator-1",
        QuarantineAction.REPROCESS,
        "fixed",
    ) is True
    update = collection.update_one.await_args.args[1]["$set"]
    assert update["retentionUntil"] > datetime.now(UTC) + timedelta(days=29)
