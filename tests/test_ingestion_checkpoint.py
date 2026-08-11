"""Contract tests for Sprint 2 checkpoint persistence and recovery state."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pymongo.errors import DuplicateKeyError

from src.domain.ingestion.checkpoints import (
    CheckpointStatus,
    IngestionCheckpoint,
    IngestionMode,
    SourceUnitStatus,
    SourceUnitSummary,
)
from src.infrastructure.ingestion.checkpoint_repository import IngestionCheckpointRepository


def _checkpoint(**overrides) -> IngestionCheckpoint:
    values: dict[str, Any] = {
        "partner": "VIETTELPAY",
        "fetch_config_id": "config-viettelpay",
        "source_type": "API",
        "stream_key": "VIETTELPAY:daily:settlement",
        "mode": IngestionMode.SCHEDULED,
    }
    values.update(overrides)
    return IngestionCheckpoint(**values)


def _repo(collection=None):
    db = MagicMock()
    db.__getitem__.return_value = collection or AsyncMock()
    return IngestionCheckpointRepository(db)


class _AsyncCursor:
    def __init__(self, documents):
        self.documents = iter(documents)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.documents)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class TestIngestionCheckpointModel:
    def test_serializes_identity_and_recovery_fields_with_camel_case(self):
        checkpoint = _checkpoint(
            current_unit_key="page:1",
            cursor_before="cursor-0",
            status=CheckpointStatus.PROCESSING,
        )

        data = checkpoint.model_dump(by_alias=True)

        assert data["fetchConfigId"] == "config-viettelpay"
        assert data["streamKey"] == "VIETTELPAY:daily:settlement"
        assert data["currentUnitKey"] == "page:1"
        assert data["cursorBefore"] == "cursor-0"
        assert data["status"] == "PROCESSING"

    def test_scheduled_and_backfill_modes_are_distinct(self):
        scheduled = _checkpoint(mode=IngestionMode.SCHEDULED)
        backfill = _checkpoint(mode=IngestionMode.BACKFILL)

        assert scheduled.mode != backfill.mode
        assert scheduled.model_dump(by_alias=True)["mode"] == "SCHEDULED"
        assert backfill.model_dump(by_alias=True)["mode"] == "BACKFILL"

    def test_blocked_retry_metadata_serializes_with_camel_case(self):
        checkpoint = _checkpoint(
            status=CheckpointStatus.BLOCKED,
            error_code="pagination_parse_error",
            retryable=False,
            next_retry_at=None,
            blocked_reason="Response schema is invalid",
        )

        data = checkpoint.model_dump(by_alias=True)

        assert data["status"] == "BLOCKED"
        assert data["errorCode"] == "pagination_parse_error"
        assert data["retryable"] is False
        assert data["blockedReason"] == "Response schema is invalid"

    def test_serializes_typed_unit_timeline_without_raw_source_metadata(self):
        checkpoint = _checkpoint(
            unit_timeline=[
                SourceUnitSummary(
                    unit_key="page:1",
                    page=1,
                    status=SourceUnitStatus.COMPLETED,
                    cursor_after="cursor-1",
                )
            ]
        )

        data = checkpoint.model_dump(by_alias=True)

        assert data["unitTimeline"][0]["unitKey"] == "page:1"
        assert data["unitTimeline"][0]["status"] == "COMPLETED"
        assert data["unitTimeline"][0]["cursorAfter"] == "cursor-1"
        assert "password" not in data["unitTimeline"][0]


class TestIngestionCheckpointRepository:
    @pytest.mark.asyncio
    async def test_create_or_get_resolves_unique_stream_race(self):
        collection = AsyncMock()
        collection.insert_one.side_effect = DuplicateKeyError("duplicate stream")
        existing = _checkpoint(status=CheckpointStatus.FAILED).model_dump(by_alias=True)
        collection.find_one.side_effect = [None, existing]
        repo = _repo(collection)

        result, created = await repo.create_or_get(_checkpoint())

        assert created is False
        assert result.status == CheckpointStatus.FAILED
        assert collection.find_one.await_count == 2

    @pytest.mark.asyncio
    async def test_concurrent_claim_has_one_winner(self):
        collection = AsyncMock()
        existing = _checkpoint().model_dump(by_alias=True)
        claimed = _checkpoint(
            status=CheckpointStatus.PROCESSING,
            current_unit_key="page:2",
            claim_id="winner",
            attempt_count=1,
        ).model_dump(by_alias=True)
        collection.find_one.return_value = existing
        collection.find_one_and_update.side_effect = [claimed, None]
        collection.find_one.side_effect = [existing, existing, claimed]
        repo = _repo(collection)

        first, first_won = await repo.claim_unit(
            partner="VIETTELPAY",
            fetch_config_id="config-viettelpay",
            source_type="API",
            stream_key="VIETTELPAY:daily:settlement",
            unit_key="page:2",
        )
        second, second_won = await repo.claim_unit(
            partner="VIETTELPAY",
            fetch_config_id="config-viettelpay",
            source_type="API",
            stream_key="VIETTELPAY:daily:settlement",
            unit_key="page:2",
        )

        assert first_won is True
        assert second_won is False
        assert first.current_unit_key == "page:2"
        assert second.current_unit_key == "page:2"
        assert collection.find_one_and_update.await_count == 2

    @pytest.mark.asyncio
    async def test_claim_persists_processing_unit_in_timeline(self):
        collection = AsyncMock()
        existing = _checkpoint().model_dump(by_alias=True)
        claimed = _checkpoint(
            status=CheckpointStatus.PROCESSING,
            current_unit_key="page:2",
            attempt_count=1,
            unit_timeline=[
                SourceUnitSummary(
                    unit_key="page:2",
                    page=2,
                    status=SourceUnitStatus.PROCESSING,
                    attempt_count=1,
                    cursor_before="cursor-1",
                )
            ],
        ).model_dump(by_alias=True)
        collection.find_one.return_value = existing
        collection.find_one_and_update.return_value = claimed
        repo = _repo(collection)

        result, won = await repo.claim_unit(
            partner="VIETTELPAY",
            fetch_config_id="config-viettelpay",
            source_type="API",
            stream_key="VIETTELPAY:daily:settlement",
            unit_key="page:2",
            cursor_before="cursor-1",
            stream_metadata={"page": 2},
        )

        assert won is True
        assert result.unit_timeline[0].status == SourceUnitStatus.PROCESSING
        update = collection.find_one_and_update.await_args.args[1]
        timeline = update["$set"]["unitTimeline"]
        assert timeline[0]["unitKey"] == "page:2"
        assert timeline[0]["page"] == 2
        assert timeline[0]["attemptCount"] == 1
        assert timeline[0]["status"] == "PROCESSING"

    @pytest.mark.asyncio
    async def test_new_source_unit_starts_a_fresh_attempt_budget(self):
        collection = AsyncMock()
        existing = _checkpoint(
            status=CheckpointStatus.DISCOVERED,
            last_completed_unit_key="page:1",
            attempt_count=1,
            unit_timeline=[
                SourceUnitSummary(
                    unit_key="page:1",
                    page=1,
                    status=SourceUnitStatus.COMPLETED,
                    attempt_count=1,
                )
            ],
        ).model_dump(by_alias=True)
        claimed = _checkpoint(
            status=CheckpointStatus.PROCESSING,
            current_unit_key="page:2",
            attempt_count=1,
            unit_timeline=[
                SourceUnitSummary(
                    unit_key="page:1",
                    page=1,
                    status=SourceUnitStatus.COMPLETED,
                    attempt_count=1,
                ),
                SourceUnitSummary(
                    unit_key="page:2",
                    page=2,
                    status=SourceUnitStatus.PROCESSING,
                    attempt_count=1,
                ),
            ],
        ).model_dump(by_alias=True)
        collection.find_one.return_value = existing
        collection.find_one_and_update.return_value = claimed
        repo = _repo(collection)

        await repo.claim_unit(
            partner="VIETTELPAY",
            fetch_config_id="config-viettelpay",
            source_type="API",
            stream_key="VIETTELPAY:daily:settlement",
            unit_key="page:2",
            expected_previous_unit_key="page:1",
            max_attempts=3,
        )

        update = collection.find_one_and_update.await_args.args[1]
        assert update["$set"]["attemptCount"] == 1
        assert update["$set"]["unitTimeline"][1]["attemptCount"] == 1
        assert "$inc" not in update

    @pytest.mark.asyncio
    async def test_retrying_same_source_unit_increments_only_that_unit(self):
        collection = AsyncMock()
        existing = _checkpoint(
            status=CheckpointStatus.FAILED,
            current_unit_key="page:2",
            last_completed_unit_key="page:1",
            attempt_count=1,
            retryable=True,
            unit_timeline=[
                SourceUnitSummary(
                    unit_key="page:1",
                    page=1,
                    status=SourceUnitStatus.COMPLETED,
                    attempt_count=1,
                ),
                SourceUnitSummary(
                    unit_key="page:2",
                    page=2,
                    status=SourceUnitStatus.FAILED,
                    attempt_count=1,
                    retryable=True,
                ),
            ],
        ).model_dump(by_alias=True)
        claimed = _checkpoint(
            status=CheckpointStatus.PROCESSING,
            current_unit_key="page:2",
            attempt_count=2,
            unit_timeline=[
                SourceUnitSummary(
                    unit_key="page:1",
                    page=1,
                    status=SourceUnitStatus.COMPLETED,
                    attempt_count=1,
                ),
                SourceUnitSummary(
                    unit_key="page:2",
                    page=2,
                    status=SourceUnitStatus.PROCESSING,
                    attempt_count=2,
                ),
            ],
        ).model_dump(by_alias=True)
        collection.find_one.return_value = existing
        collection.find_one_and_update.return_value = claimed
        repo = _repo(collection)

        await repo.claim_unit(
            partner="VIETTELPAY",
            fetch_config_id="config-viettelpay",
            source_type="API",
            stream_key="VIETTELPAY:daily:settlement",
            unit_key="page:2",
            expected_previous_unit_key="page:1",
            max_attempts=3,
        )

        update = collection.find_one_and_update.await_args.args[1]
        assert update["$set"]["attemptCount"] == 2
        assert update["$set"]["unitTimeline"][1]["attemptCount"] == 2

    @pytest.mark.asyncio
    async def test_find_by_streams_batches_recovery_lookup_without_endpoint_leak(self):
        collection = AsyncMock()
        collection.find = MagicMock(return_value=_AsyncCursor([]))
        repo = _repo(collection)

        result = await repo.find_by_streams([
            {
                "partner": "VIETTELPAY",
                "fetchConfigId": "config-viettelpay",
                "sourceType": "API",
                "streamKey": None,
                "mode": IngestionMode.SCHEDULED,
            }
        ])

        assert result == []
        query = collection.find.call_args.args[0]
        assert len(query["$or"]) == 1
        assert query["$or"][0]["streamKey"] == {"$exists": True}

    @pytest.mark.asyncio
    async def test_stale_processing_claim_can_be_reclaimed_after_restart(self):
        collection = AsyncMock()
        stale = _checkpoint(
            status=CheckpointStatus.PROCESSING,
            current_unit_key="page:2",
            claim_id="old-worker",
            started_at=datetime.now(UTC) - timedelta(hours=1),
        )
        claimed = stale.model_copy(
            update={"claim_id": "new-worker", "attempt_count": 2}
        ).model_dump(by_alias=True)
        collection.find_one.return_value = stale.model_dump(by_alias=True)
        collection.find_one_and_update.return_value = claimed
        repo = _repo(collection)

        result, won = await repo.claim_unit(
            partner="VIETTELPAY",
            fetch_config_id="config-viettelpay",
            source_type="API",
            stream_key="VIETTELPAY:daily:settlement",
            unit_key="page:2",
            claim_timeout_seconds=60,
        )

        assert won is True
        assert result.claim_id == "new-worker"
        query = collection.find_one_and_update.await_args.args[0]
        assert query["$or"][1]["status"] == "PROCESSING"
        assert query["$or"][1]["startedAt"]["$lte"] < datetime.now(UTC)

    @pytest.mark.asyncio
    async def test_claim_requires_the_expected_previous_boundary_and_attempt_limit(self):
        collection = AsyncMock()
        existing = _checkpoint(
            status=CheckpointStatus.COMPLETED,
            last_completed_unit_key="page:1",
        ).model_dump(by_alias=True)
        collection.find_one.return_value = existing
        collection.find_one_and_update.return_value = existing
        repo = _repo(collection)

        await repo.claim_unit(
            partner="VIETTELPAY",
            fetch_config_id="config-viettelpay",
            source_type="API",
            stream_key="VIETTELPAY:daily:settlement",
            unit_key="page:2",
            expected_previous_unit_key="page:1",
            max_attempts=3,
        )

        query = collection.find_one_and_update.await_args.args[0]
        assert query["lastCompletedUnitKey"] == "page:1"
        assert query["$or"][1]["attemptCount"] == {"$lt": 3}

    @pytest.mark.asyncio
    async def test_review_wait_releases_processing_claim_without_advancing_boundary(self):
        collection = AsyncMock()
        collection.update_one.return_value = MagicMock(modified_count=1)
        repo = _repo(collection)
        checkpoint = _checkpoint(
            status=CheckpointStatus.PROCESSING,
            current_unit_key="file:pending-review",
            claim_id="claim-review",
        )

        released = await repo.release_for_review(
            checkpoint,
            unit_key="file:pending-review",
            reason="Mapping approval is required",
        )

        assert released is True
        query = collection.update_one.await_args.args[0]
        update = collection.update_one.await_args.args[1]
        assert query["status"] == "PROCESSING"
        assert query["currentUnitKey"] == "file:pending-review"
        assert update["$set"]["status"] == "DISCOVERED"
        assert update["$set"]["currentUnitKey"] is None
        assert update["$set"]["claimId"] is None
        assert update["$set"]["errorCode"] == "configuration_approval_required"

    @pytest.mark.asyncio
    async def test_failed_unit_can_retry_and_completed_unit_cannot_move_backward(self):
        collection = AsyncMock()
        checkpoint = _checkpoint(
            status=CheckpointStatus.PROCESSING,
            current_unit_key="page:2",
            claim_id="claim-1",
        )
        collection.find_one.return_value = checkpoint.model_dump(by_alias=True)
        failed_result = MagicMock(modified_count=1)
        completed_result = MagicMock(modified_count=1)
        stale_advance_result = MagicMock(modified_count=0)
        collection.update_one.side_effect = [
            failed_result,
            completed_result,
            stale_advance_result,
        ]
        repo = _repo(collection)

        assert await repo.mark_failed(
            checkpoint,
            unit_key="page:2",
            error="timeout",
        )
        assert await repo.mark_completed(
            checkpoint,
            unit_key="page:2",
            cursor_after="cursor-2",
        )
        assert not await repo.advance(checkpoint, unit_key="page:1")

        failed_update = collection.update_one.await_args_list[0].args[1]
        completed_update = collection.update_one.await_args_list[1].args[1]
        assert failed_update["$set"]["status"] == "FAILED"
        assert completed_update["$set"]["lastCompletedUnitKey"] == "page:2"
        assert completed_update["$set"]["cursorAfter"] == "cursor-2"

    @pytest.mark.asyncio
    async def test_retryable_failure_persists_backoff_and_error_code(self):
        collection = AsyncMock()
        collection.update_one.return_value = MagicMock(modified_count=1)
        repo = _repo(collection)
        checkpoint = _checkpoint(
            status=CheckpointStatus.PROCESSING,
            current_unit_key="page:2",
            claim_id="claim-1",
            attempt_count=1,
        )
        retry_at = datetime.now(UTC) + timedelta(minutes=1)

        assert await repo.mark_failed(
            checkpoint,
            unit_key="page:2",
            error="gateway timeout",
            error_code="fetch_timeout",
            retryable=True,
            next_retry_at=retry_at,
            max_attempts=3,
        )

        update = collection.update_one.await_args.args[1]
        assert update["$set"]["status"] == "FAILED"
        assert update["$set"]["errorCode"] == "fetch_timeout"
        assert update["$set"]["retryable"] is True
        assert update["$set"]["nextRetryAt"] == retry_at
        assert update["$set"]["unitTimeline"][0]["status"] == "FAILED"
        assert update["$set"]["unitTimeline"][0]["attemptCount"] == 1

    @pytest.mark.asyncio
    async def test_failed_transition_appends_persisted_recovery_event(self):
        collection = AsyncMock()
        collection.update_one.return_value = MagicMock(modified_count=1)
        repo = _repo(collection)
        checkpoint = _checkpoint(
            status=CheckpointStatus.PROCESSING,
            current_unit_key="page:2",
            claim_id="claim-1",
        )

        assert await repo.mark_failed(
            checkpoint,
            unit_key="page:2",
            error="gateway timeout",
            error_code="fetch_timeout",
        )

        update = collection.update_one.await_args.args[1]
        event = update["$push"]["recoveryEvents"]
        assert event["unitKey"] == "page:2"
        assert event["status"] == "FAILED"
        assert event["errorCode"] == "fetch_timeout"

    @pytest.mark.asyncio
    async def test_manual_retry_clears_backoff_and_records_operator(self):
        collection = AsyncMock()
        collection.update_one.return_value = MagicMock(modified_count=1)
        repo = _repo(collection)
        checkpoint = _checkpoint(
            status=CheckpointStatus.FAILED,
            current_unit_key="page:2",
            attempt_count=2,
            retryable=True,
            next_retry_at=datetime.now(UTC) + timedelta(minutes=1),
            unit_timeline=[
                SourceUnitSummary(
                    unit_key="page:2",
                    page=2,
                    status=SourceUnitStatus.FAILED,
                    attempt_count=2,
                    error_code="fetch_timeout",
                    retryable=True,
                )
            ],
        )

        prepared = await repo.prepare_manual_retry(
            checkpoint,
            operator_id="ops-user",
            reason="Operator requested immediate retry",
        )

        assert prepared is True
        query = collection.update_one.await_args.args[0]
        update = collection.update_one.await_args.args[1]
        assert query["status"] == "FAILED"
        assert query["retryable"] is True
        assert update["$set"]["nextRetryAt"] is None
        assert update["$set"]["resolutionMetadata"]["operatorId"] == "ops-user"
        assert update["$set"]["unitTimeline"][0]["nextRetryAt"] is None
        assert update["$push"]["recoveryEvents"]["status"] == "RETRY_REQUESTED"
        assert update["$push"]["recoveryEvents"]["action"] == "RETRY"

    @pytest.mark.asyncio
    async def test_terminal_or_exhausted_failure_becomes_blocked(self):
        collection = AsyncMock()
        collection.update_one.return_value = MagicMock(modified_count=1)
        repo = _repo(collection)
        checkpoint = _checkpoint(
            status=CheckpointStatus.PROCESSING,
            current_unit_key="day:2",
            claim_id="claim-1",
            attempt_count=3,
        )

        assert await repo.mark_failed(
            checkpoint,
            unit_key="day:2",
            error="invalid response schema",
            error_code="pagination_parse_error",
            retryable=False,
            max_attempts=3,
        )

        update = collection.update_one.await_args.args[1]
        assert update["$set"]["status"] == "BLOCKED"
        assert update["$set"]["blockedReason"] == "invalid response schema"
        assert update["$set"]["nextRetryAt"] is None

    @pytest.mark.asyncio
    async def test_operator_can_resolve_blocked_unit_with_audited_action(self):
        collection = AsyncMock()
        collection.update_one.return_value = MagicMock(modified_count=1)
        repo = _repo(collection)
        checkpoint = _checkpoint(
            status=CheckpointStatus.BLOCKED,
            current_unit_key="day:2",
            claim_id="claim-1",
        )

        assert await repo.resolve_blocked(
            checkpoint,
            unit_key="day:2",
            action="RETRY",
            reason="Credential was corrected",
            operator_id="ops-user",
        )

        query = collection.update_one.await_args.args[0]
        update = collection.update_one.await_args.args[1]
        assert query["status"] == "BLOCKED"
        assert update["$set"]["status"] == "DISCOVERED"
        assert update["$set"]["resolutionMetadata"]["action"] == "RETRY"
        assert update["$set"]["resolutionMetadata"]["operatorId"] == "ops-user"

    @pytest.mark.asyncio
    async def test_advance_only_releases_a_completed_boundary(self):
        collection = AsyncMock()
        collection.update_one.return_value = MagicMock(modified_count=1)
        repo = _repo(collection)
        checkpoint = _checkpoint(
            status=CheckpointStatus.COMPLETED,
            current_unit_key="page:1",
            last_completed_unit_key="page:1",
        )

        assert await repo.advance(checkpoint, unit_key="page:1")
        query = collection.update_one.await_args.args[0]
        update = collection.update_one.await_args.args[1]
        assert query["lastCompletedUnitKey"] == "page:1"
        assert query["status"] == "COMPLETED"
        assert update["$set"]["status"] == "DISCOVERED"
        assert update["$set"]["currentUnitKey"] is None
