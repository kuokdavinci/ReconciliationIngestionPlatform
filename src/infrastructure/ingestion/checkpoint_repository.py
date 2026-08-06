"""MongoDB adapter for incremental ingestion checkpoints."""

from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from src.domain.ingestion.checkpoints import (
    CheckpointRepository,
    CheckpointStatus,
    IngestionCheckpoint,
    IngestionMode,
)
from src.infrastructure.persistence.mongo_repository import BaseRepository


class IngestionCheckpointRepository(BaseRepository[IngestionCheckpoint], CheckpointRepository):
    """Repository implementing atomic source-unit claim and transitions."""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="ingestion_checkpoint", db=db)
        self._set_model_class(IngestionCheckpoint)

    @staticmethod
    def _stream_filter(*, partner: str, fetch_config_id: str, source_type: str, stream_key: str, mode: IngestionMode) -> dict[str, Any]:
        return {
            "partner": partner,
            "fetchConfigId": fetch_config_id,
            "sourceType": source_type,
            "streamKey": stream_key,
            "mode": mode.value,
        }

    async def find_by_stream(self, *, partner: str, fetch_config_id: str, source_type: str, stream_key: str, mode: IngestionMode = IngestionMode.SCHEDULED) -> Optional[IngestionCheckpoint]:
        return await self.find_one(self._stream_filter(partner=partner, fetch_config_id=fetch_config_id, source_type=source_type, stream_key=stream_key, mode=mode))

    async def create_or_get(self, checkpoint: IngestionCheckpoint) -> tuple[IngestionCheckpoint, bool]:
        identity = self._stream_filter(partner=checkpoint.partner, fetch_config_id=checkpoint.fetch_config_id, source_type=checkpoint.source_type, stream_key=checkpoint.stream_key, mode=checkpoint.mode)
        existing = await self.find_one(identity)
        if existing is not None:
            return existing, False
        try:
            return await self.create(checkpoint), True
        except DuplicateKeyError:
            existing = await self.find_one(identity)
            if existing is None:
                raise
            return existing, False

    async def claim_unit(self, *, partner: str, fetch_config_id: str, source_type: str, stream_key: str, unit_key: str, mode: IngestionMode = IngestionMode.SCHEDULED, cursor_before: Optional[str] = None, expected_previous_unit_key: Optional[str] = None, max_attempts: Optional[int] = None, config_version: Optional[str] = None, source_endpoint: Optional[str] = None, stream_metadata: Optional[dict[str, Any]] = None, claim_timeout_seconds: int = 900) -> tuple[IngestionCheckpoint, bool]:
        identity = self._stream_filter(partner=partner, fetch_config_id=fetch_config_id, source_type=source_type, stream_key=stream_key, mode=mode)
        checkpoint, _ = await self.create_or_get(
            IngestionCheckpoint.model_validate(
                {
                    **identity,
                    "configVersion": config_version,
                    "sourceEndpoint": source_endpoint,
                    "streamMetadata": stream_metadata or {},
                }
            )
        )
        if checkpoint.last_completed_unit_key == unit_key:
            return checkpoint, False
        now = datetime.now(UTC)
        claim_id = str(uuid4())
        if claim_timeout_seconds < 0:
            raise ValueError("claim_timeout_seconds must be non-negative")
        if max_attempts is not None and max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        query = {
            **identity,
            "lastCompletedUnitKey": expected_previous_unit_key,
            "$or": [
                {"$or": [
                    {"status": {"$in": [CheckpointStatus.ABSENT.value, CheckpointStatus.DISCOVERED.value, CheckpointStatus.COMPLETED.value]}},
                    {"status": CheckpointStatus.FAILED.value, "retryable": {"$ne": False}, "$or": [{"nextRetryAt": None}, {"nextRetryAt": {"$lte": now}}]},
                ]},
                {
                    "status": CheckpointStatus.PROCESSING.value,
                    "startedAt": {"$lte": now - timedelta(seconds=claim_timeout_seconds)},
                    **(
                        {"attemptCount": {"$lt": max_attempts}}
                        if max_attempts is not None
                        else {}
                    ),
                },
            ],
        }
        update = {
            "$set": {
                "currentUnitKey": unit_key,
                "cursorBefore": cursor_before,
                "status": CheckpointStatus.PROCESSING.value,
                "claimId": claim_id,
                "lastError": None,
                "errorCode": None,
                "retryable": None,
                "nextRetryAt": None,
                "blockedAt": None,
                "blockedReason": None,
                "lastErrorMetadata": {},
                "startedAt": now,
                "completedAt": None,
                "updatedAt": now,
                "configVersion": config_version,
                "sourceEndpoint": source_endpoint,
                "streamMetadata": stream_metadata or {},
            },
            "$inc": {"attemptCount": 1},
        }
        raw = await self.collection.find_one_and_update(query, update, return_document=ReturnDocument.AFTER)
        if raw is not None:
            return self._from_mongo(raw), True
        existing = await self.find_one(identity)
        if existing is None:
            raise RuntimeError("Checkpoint disappeared while claiming source unit")
        if (
            max_attempts is not None
            and existing.status == CheckpointStatus.PROCESSING
            and existing.attempt_count >= max_attempts
        ):
            stale_query = {
                **identity,
                "currentUnitKey": existing.current_unit_key,
                "status": CheckpointStatus.PROCESSING.value,
            }
            await self.collection.update_one(
                stale_query,
                {
                    "$set": {
                        "status": CheckpointStatus.BLOCKED.value,
                        "retryable": False,
                        "blockedAt": now,
                        "blockedReason": "Maximum source-unit attempts exhausted.",
                        "updatedAt": now,
                    }
                },
            )
        return existing, False

    async def mark_failed(self, checkpoint: IngestionCheckpoint, *, unit_key: str, error: str, error_code: str = "source_unit_failed", retryable: bool = True, next_retry_at: Optional[datetime] = None, max_attempts: Optional[int] = None, error_metadata: Optional[dict[str, Any]] = None) -> bool:
        if max_attempts is not None and max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        blocked = not retryable or (max_attempts is not None and checkpoint.attempt_count >= max_attempts)
        now = datetime.now(UTC)
        query = {**self._stream_filter(partner=checkpoint.partner, fetch_config_id=checkpoint.fetch_config_id, source_type=checkpoint.source_type, stream_key=checkpoint.stream_key, mode=checkpoint.mode), "currentUnitKey": unit_key, "status": CheckpointStatus.PROCESSING.value, "claimId": checkpoint.claim_id}
        result = await self.collection.update_one(query, {"$set": {"status": CheckpointStatus.BLOCKED.value if blocked else CheckpointStatus.FAILED.value, "lastError": error, "errorCode": error_code, "retryable": retryable, "nextRetryAt": None if blocked else next_retry_at, "blockedAt": now if blocked else None, "blockedReason": error if blocked else None, "lastErrorMetadata": error_metadata or {}, "updatedAt": now}})
        return result.modified_count == 1

    async def release_for_review(
        self,
        checkpoint: IngestionCheckpoint,
        *,
        unit_key: str,
        reason: str,
    ) -> bool:
        """Release a claimed unit without advancing it while review is pending."""
        query = {
            **self._stream_filter(
                partner=checkpoint.partner,
                fetch_config_id=checkpoint.fetch_config_id,
                source_type=checkpoint.source_type,
                stream_key=checkpoint.stream_key,
                mode=checkpoint.mode,
            ),
            "currentUnitKey": unit_key,
            "status": CheckpointStatus.PROCESSING.value,
            "claimId": checkpoint.claim_id,
        }
        now = datetime.now(UTC)
        result = await self.collection.update_one(
            query,
            {
                "$set": {
                    "status": CheckpointStatus.DISCOVERED.value,
                    "currentUnitKey": None,
                    "claimId": None,
                    "lastError": reason,
                    "errorCode": "configuration_approval_required",
                    "retryable": None,
                    "nextRetryAt": None,
                    "blockedAt": None,
                    "blockedReason": None,
                    "startedAt": None,
                    "updatedAt": now,
                }
            },
        )
        return result.modified_count == 1

    async def resolve_blocked(self, checkpoint: IngestionCheckpoint, *, unit_key: str, action: str, reason: str, operator_id: str) -> bool:
        if action not in {"RETRY", "SKIP"}:
            raise ValueError("action must be RETRY or SKIP")
        query = {**self._stream_filter(partner=checkpoint.partner, fetch_config_id=checkpoint.fetch_config_id, source_type=checkpoint.source_type, stream_key=checkpoint.stream_key, mode=checkpoint.mode), "currentUnitKey": unit_key, "status": CheckpointStatus.BLOCKED.value}
        now = datetime.now(UTC)
        result = await self.collection.update_one(query, {"$set": {"status": CheckpointStatus.DISCOVERED.value, "retryable": True, "nextRetryAt": None, "blockedAt": None, "blockedReason": None, "resolutionMetadata": {"action": action, "reason": reason, "operatorId": operator_id, "resolvedAt": now}, "updatedAt": now}})
        return result.modified_count == 1

    async def mark_completed(self, checkpoint: IngestionCheckpoint, *, unit_key: str, cursor_after: Optional[str] = None, high_water_mark: Optional[dict[str, Any]] = None) -> bool:
        query = {**self._stream_filter(partner=checkpoint.partner, fetch_config_id=checkpoint.fetch_config_id, source_type=checkpoint.source_type, stream_key=checkpoint.stream_key, mode=checkpoint.mode), "currentUnitKey": unit_key, "status": CheckpointStatus.PROCESSING.value, "claimId": checkpoint.claim_id}
        now = datetime.now(UTC)
        result = await self.collection.update_one(query, {"$set": {"status": CheckpointStatus.COMPLETED.value, "lastCompletedUnitKey": unit_key, "cursorAfter": cursor_after, "highWaterMark": high_water_mark, "lastError": None, "errorCode": None, "retryable": None, "nextRetryAt": None, "blockedAt": None, "blockedReason": None, "resolutionMetadata": {}, "completedAt": now, "updatedAt": now, "lastErrorMetadata": {}}})
        return result.modified_count == 1

    async def advance(self, checkpoint: IngestionCheckpoint, *, unit_key: str) -> bool:
        query = {**self._stream_filter(partner=checkpoint.partner, fetch_config_id=checkpoint.fetch_config_id, source_type=checkpoint.source_type, stream_key=checkpoint.stream_key, mode=checkpoint.mode), "currentUnitKey": unit_key, "lastCompletedUnitKey": unit_key, "status": CheckpointStatus.COMPLETED.value}
        result = await self.collection.update_one(query, {"$set": {"status": CheckpointStatus.DISCOVERED.value, "currentUnitKey": None, "updatedAt": datetime.now(UTC)}})
        return result.modified_count == 1

    async def find_pending_or_failed(self, *, mode: Optional[IngestionMode] = None) -> list[IngestionCheckpoint]:
        now = datetime.now(UTC)
        query: dict[str, Any] = {"$or": [{"status": {"$in": [CheckpointStatus.ABSENT.value, CheckpointStatus.DISCOVERED.value]}}, {"status": CheckpointStatus.FAILED.value, "retryable": {"$ne": False}, "$or": [{"nextRetryAt": None}, {"nextRetryAt": {"$lte": now}}]}]}
        if mode is not None:
            query["mode"] = mode.value
        cursor = self.collection.find(query).sort("updatedAt", 1)
        results = []
        async for raw in cursor:
            results.append(self._from_mongo(raw))
        return results
