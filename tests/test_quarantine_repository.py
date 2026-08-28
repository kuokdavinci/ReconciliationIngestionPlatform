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
from src.domain.ingestion import quarantine
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
    assert update["$set"]["lastActionId"] is None


@pytest.mark.asyncio
async def test_claim_records_action_metadata_when_action_id_is_supplied():
    record, pending = _record()
    _, reprocessing = _record(QuarantineStatus.REPROCESSING)
    reprocessing["_id"] = str(record.id)
    reprocessing["claimedBy"] = "operator-1"
    reprocessing["lastActionId"] = "act-claim"
    repository, collection = _repository()
    collection.find_one = AsyncMock(return_value=pending)
    collection.find_one_and_update = AsyncMock(return_value=reprocessing)

    await repository.claim(str(record.id), "operator-1", lease_seconds=120, action_id="act-claim")

    _, update = collection.find_one_and_update.call_args.args[:2]
    event = update["$push"]["resolutionHistory"]
    assert update["$set"]["lastActionId"] == "act-claim"
    assert event["actionId"] == "act-claim"
    assert event["outcome"] == "CLAIMED"


@pytest.mark.asyncio
async def test_reserve_action_uses_atomic_document_reservation():
    record, pending = _record()
    pending["_id"] = str(record.id)
    repository, collection = _repository()
    collection.find_one_and_update = AsyncMock(return_value=pending)

    result = await repository.reserve_action(
        str(record.id),
        "operator-1",
        "act-reprocess",
        QuarantineAction.REPROCESS,
    )

    assert result == "RESERVED"
    query, update = collection.find_one_and_update.call_args.args[:2]
    assert query["_id"] == str(record.id)
    assert query["$or"] == [
        {"activeActionId": {"$exists": False}},
        {"activeActionId": None},
    ]
    assert query["resolutionHistory.actionId"] == {"$ne": "act-reprocess"}
    assert update["$set"]["activeActionId"] == "act-reprocess"
    assert update["$set"]["activeActionActor"] == "operator-1"
    assert update["$set"]["activeAction"] == "REPROCESS"


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
async def test_claim_does_not_accept_non_pending_expected_status_override():
    record, reprocessing = _record(QuarantineStatus.REPROCESSING)
    reprocessing["_id"] = str(record.id)
    reprocessing["claimedBy"] = "operator-1"
    repository, collection = _repository()
    collection.find_one = AsyncMock(return_value=reprocessing)
    collection.find_one_and_update = AsyncMock()

    with pytest.raises(TypeError):
        await repository.claim(
            str(record.id),
            "operator-2",
            expected_status=QuarantineStatus.REPROCESSING,
        )

    collection.find_one_and_update.assert_not_called()


def test_repository_does_not_expose_unbound_mark_status_mutation():
    repository, _ = _repository()

    assert getattr(repository, "mark_status", None) is None


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
    event = update["$push"]["resolutionHistory"]
    assert event["action"] == "REPROCESS"
    assert event["metadata"] == {"source": "test"}


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
async def test_expired_claim_cannot_be_released_or_resolved():
    record, reprocessing = _record(QuarantineStatus.REPROCESSING)
    reprocessing["_id"] = str(record.id)
    reprocessing["claimedBy"] = "operator-1"
    reprocessing["claimExpiresAt"] = datetime(2026, 8, 26, tzinfo=UTC)
    repository, collection = _repository()
    collection.find_one = AsyncMock(return_value=reprocessing)
    collection.update_one = AsyncMock(
        return_value=SimpleNamespace(modified_count=1)
    )

    released = await repository.release_for_retry(
        str(record.id), "operator-1", "Retry requested.", {}
    )
    resolved = await repository.resolve(
        str(record.id),
        QuarantineStatus.RESOLVED,
        "operator-1",
        QuarantineAction.REPROCESS,
        "Resolved.",
    )

    assert released is False
    assert resolved is False
    collection.update_one.assert_not_called()


@pytest.mark.asyncio
async def test_expired_claim_can_be_reclaimed_to_pending():
    record, expired = _record(QuarantineStatus.REPROCESSING)
    expired["_id"] = str(record.id)
    expired["claimedBy"] = "operator-1"
    expired["claimExpiresAt"] = datetime(2026, 8, 26, tzinfo=UTC)
    _, pending = _record(QuarantineStatus.PENDING)
    pending["_id"] = str(record.id)
    repository, collection = _repository()
    collection.find_one_and_update = AsyncMock(return_value=pending)

    reclaimed = await repository.reclaim_expired_claim(str(record.id))

    assert reclaimed is not None
    assert reclaimed.status is QuarantineStatus.PENDING
    query, update = collection.find_one_and_update.call_args.args[:2]
    assert query["_id"] == str(record.id)
    assert query["status"] == QuarantineStatus.REPROCESSING.value
    assert isinstance(query["claimExpiresAt"]["$lte"], datetime)
    assert update["$set"]["status"] == QuarantineStatus.PENDING.value
    assert update["$set"]["claimedBy"] is None


@pytest.mark.asyncio
async def test_retry_and_resolve_cas_writes_bound_action_metadata():
    record, reprocessing = _record(QuarantineStatus.REPROCESSING)
    reprocessing["_id"] = str(record.id)
    reprocessing["claimedBy"] = "operator-1"
    repository, collection = _repository()
    collection.find_one = AsyncMock(return_value=reprocessing)
    collection.update_one = AsyncMock(return_value=SimpleNamespace(modified_count=1))

    released = await repository.release_for_retry(
        str(record.id),
        "operator-1",
        "x" * 600,
        {"error": "raw stack", "retryable": True},
        action_id="act-retry",
        outcome="VALIDATION_FAILED",
    )

    assert released is True
    retry_query, retry_update = collection.update_one.call_args.args
    retry_event = retry_update["$push"]["resolutionHistory"]
    assert retry_query["status"] == QuarantineStatus.REPROCESSING.value
    assert retry_query["claimedBy"] == "operator-1"
    assert retry_update["$set"]["lastActionId"] == "act-retry"
    assert retry_update["$set"]["lastAttemptError"] == "x" * 500
    assert retry_event["actionId"] == "act-retry"
    assert retry_event["outcome"] == "VALIDATION_FAILED"
    assert retry_event["reason"] == "x" * 500
    assert retry_event["metadata"] == {"retryable": True}

    collection.update_one.reset_mock()
    resolved = await repository.resolve(
        str(record.id),
        QuarantineStatus.RESOLVED,
        "operator-1",
        QuarantineAction.REPROCESS,
        "Resolved",
        {"existingFingerprint": "secret-fingerprint", "origin": "SOURCE"},
        action_id="act-resolve",
        outcome="RESOLVED",
    )

    assert resolved is True
    _, resolve_update = collection.update_one.call_args.args
    resolve_event = resolve_update["$push"]["resolutionHistory"]
    assert resolve_update["$set"]["lastActionId"] == "act-resolve"
    assert resolve_update["$set"]["resolutionMetadata"] == {"origin": "SOURCE"}
    assert resolve_event["actionId"] == "act-resolve"
    assert resolve_event["outcome"] == "RESOLVED"


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
    third, third_raw = _record()
    third_raw["_id"] = str(third.id)
    third_raw["createdAt"] = datetime(2026, 8, 27, tzinfo=UTC)
    cursor = _AsyncCursor([first_raw, second_raw, third_raw])
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
    assert cursor.limit_value == 3
    assert len(records) == 2
    assert next_cursor is not None


@pytest.mark.asyncio
async def test_find_many_omits_cursor_when_page_is_not_full():
    query_model = getattr(quarantine, "QuarantineQuery", None)
    assert query_model is not None
    record, raw = _record()
    raw["_id"] = str(record.id)
    repository, collection = _repository()
    collection.find.return_value = _AsyncCursor([raw])

    records, next_cursor = await repository.find_many(
        query_model(partner="MOMO", limit=2)
    )

    assert len(records) == 1
    assert next_cursor is None


@pytest.mark.asyncio
async def test_find_many_adds_operator_priority_and_overdue_filters():
    priority_model = getattr(quarantine, "QuarantinePriority", None)
    query_model = getattr(quarantine, "QuarantineQuery", None)
    assert priority_model is not None
    assert query_model is not None

    repository, collection = _repository()
    collection.find.return_value = _AsyncCursor([])
    now = datetime(2026, 8, 27, tzinfo=UTC)

    await repository.find_many(
        query_model(
            claimedBy="operator-1",
            priority=priority_model.HIGH,
            overdue=True,
            limit=10,
        ),
        now=now,
    )

    query = collection.find.call_args.args[0]
    assert query["claimedBy"] == "operator-1"
    assert query["priority"] == "HIGH"
    assert query["status"]["$in"] == ["PENDING", "REPROCESSING"]
    assert query["reviewDueAt"] == {"$lte": now}


@pytest.mark.asyncio
async def test_find_many_maps_issue_type_to_quality_codes():
    query_model = getattr(quarantine, "QuarantineQuery", None)
    issue_type_model = getattr(quarantine, "QuarantineIssueType", None)
    assert query_model is not None
    assert issue_type_model is not None

    repository, collection = _repository()
    collection.find.return_value = _AsyncCursor([])

    await repository.find_many(
        query_model(issueType=issue_type_model.DUPLICATE, limit=10)
    )

    query = collection.find.call_args.args[0]
    assert query["errors.errorCode"] == {
        "$in": ["EQUIVALENT_DUPLICATE", "CONFLICTING_DUPLICATE"]
    }


@pytest.mark.asyncio
async def test_find_action_returns_matching_resolution_event():
    record, raw = _record()
    raw["resolutionHistory"] = [
        {
            "eventId": "11111111-1111-1111-1111-111111111111",
            "fromStatus": "PENDING",
            "toStatus": "REPROCESSING",
            "action": "REPROCESS",
            "actor": "operator-1",
            "reason": "claimed",
            "attempt": 2,
            "timestamp": datetime(2026, 8, 27, tzinfo=UTC),
            "metadata": {},
            "actionId": "act-1",
            "outcome": "CLAIMED",
        }
    ]
    repository, collection = _repository()
    collection.find_one = AsyncMock(return_value=raw)

    event = await repository.find_action(str(record.id), "act-1")

    assert event is not None
    assert event.action_id == "act-1"
    assert event.outcome == "CLAIMED"
    query = collection.find_one.call_args.args[0]
    assert query == {"_id": str(record.id), "resolutionHistory.actionId": "act-1"}


@pytest.mark.asyncio
async def test_summarize_counts_filtered_queue_and_overdue_records():
    query_model = getattr(quarantine, "QuarantineQuery", None)
    assert query_model is not None

    repository, collection = _repository()
    collection.count_documents = AsyncMock(side_effect=[5, 2, 1, 3, 4, 2, 6])
    now = datetime(2026, 8, 27, tzinfo=UTC)

    summary = await repository.summarize(query_model(partner="MOMO"), now=now)

    assert summary == {
        "total": 5,
        "pending": 2,
        "reprocessing": 1,
        "resolved": 3,
        "rejected": 4,
        "overdue": 2,
        "highPriority": 6,
    }
    overdue_query = collection.count_documents.call_args_list[-2].args[0]
    assert overdue_query["$and"] == [
        {"partner": "MOMO"},
        {"status": {"$in": ["PENDING", "REPROCESSING"]}, "reviewDueAt": {"$lte": now}},
    ]


@pytest.mark.asyncio
async def test_summarize_preserves_caller_status_filter_for_buckets():
    query_model = getattr(quarantine, "QuarantineQuery", None)
    assert query_model is not None

    repository, collection = _repository()
    collection.count_documents = AsyncMock(side_effect=[7, 5, 2, 4])
    now = datetime(2026, 8, 27, tzinfo=UTC)

    summary = await repository.summarize(
        query_model(partner="MOMO", status=QuarantineStatus.PENDING),
        now=now,
    )

    assert summary == {
        "total": 7,
        "pending": 5,
        "reprocessing": 0,
        "resolved": 0,
        "rejected": 0,
        "overdue": 2,
        "highPriority": 4,
    }
    assert collection.count_documents.call_args_list[1].args[0]["$and"] == [
        {"partner": "MOMO", "status": "PENDING"},
        {"status": "PENDING"},
    ]
    assert collection.count_documents.call_args_list[2].args[0]["$and"] == [
        {"partner": "MOMO", "status": "PENDING"},
        {"status": {"$in": ["PENDING", "REPROCESSING"]}, "reviewDueAt": {"$lte": now}},
    ]


@pytest.mark.asyncio
async def test_escalate_caps_level_sets_high_priority_and_records_action():
    record, pending = _record()
    pending["escalationLevel"] = 2
    pending["reviewDueAt"] = datetime(2026, 8, 26, tzinfo=UTC)
    repository, collection = _repository()
    collection.find_one = AsyncMock(return_value=pending)
    collection.update_one = AsyncMock(return_value=SimpleNamespace(modified_count=1))

    escalated = await repository.escalate(
        str(record.id),
        "operator-1",
        "act-escalate",
        QuarantineStatus.PENDING,
        "Needs senior review",
    )

    assert escalated is not None
    query, update = collection.update_one.call_args.args
    event = update["$push"]["resolutionHistory"]
    assert query == {
        "_id": str(record.id),
        "status": "PENDING",
        "escalationLevel": 2,
        "resolutionHistory.actionId": {"$ne": "act-escalate"},
    }
    assert query["escalationLevel"] == 2
    assert "priority" not in update["$set"]
    assert update["$set"]["escalationLevel"] == 3
    assert update["$set"]["escalatedBy"] == "operator-1"
    assert update["$set"]["lastActionId"] == "act-escalate"
    assert event["action"] == "ESCALATE"
    assert event["actionId"] == "act-escalate"
    assert event["outcome"] == "ESCALATED"


@pytest.mark.asyncio
async def test_escalate_reprocessing_requires_claim_owner_and_preserves_status():
    record, reprocessing = _record(QuarantineStatus.REPROCESSING)
    reprocessing["_id"] = str(record.id)
    reprocessing["claimedBy"] = "operator-1"
    reprocessing["escalationLevel"] = 1
    repository, collection = _repository()
    collection.find_one = AsyncMock(return_value=reprocessing)
    collection.update_one = AsyncMock(return_value=SimpleNamespace(modified_count=1))

    escalated = await repository.escalate(
        str(record.id),
        "operator-1",
        "act-escalate-reprocessing",
        QuarantineStatus.REPROCESSING,
        "Needs senior review",
    )

    assert escalated is not None
    query, update = collection.update_one.call_args.args
    event = update["$push"]["resolutionHistory"]
    assert query == {
        "_id": str(record.id),
        "status": "REPROCESSING",
        "claimedBy": "operator-1",
        "escalationLevel": 1,
        "resolutionHistory.actionId": {"$ne": "act-escalate-reprocessing"},
    }
    assert query["escalationLevel"] == 1
    assert "status" not in update["$set"]
    assert "claimedBy" not in update["$set"]
    assert update["$set"]["escalationLevel"] == 2
    assert event["fromStatus"] == "REPROCESSING"
    assert event["toStatus"] == "REPROCESSING"


@pytest.mark.asyncio
async def test_escalate_at_level_three_records_noop_without_incrementing():
    record, pending = _record()
    pending["escalationLevel"] = 3
    repository, collection = _repository()
    collection.find_one = AsyncMock(return_value=pending)
    collection.update_one = AsyncMock(return_value=SimpleNamespace(modified_count=1))

    escalated = await repository.escalate(
        str(record.id),
        "operator-1",
        "act-escalate-noop",
        QuarantineStatus.PENDING,
        "Already senior review",
    )

    assert escalated is None
    collection.update_one.assert_not_called()


@pytest.mark.asyncio
async def test_summarize_includes_high_priority_count():
    query_model = getattr(quarantine, "QuarantineQuery", None)
    assert query_model is not None

    repository, collection = _repository()
    collection.count_documents = AsyncMock(side_effect=[7, 2, 1, 3, 4, 2, 5])
    now = datetime(2026, 8, 27, tzinfo=UTC)

    summary = await repository.summarize(query_model(partner="MOMO"), now=now)

    assert summary["highPriority"] == 5
