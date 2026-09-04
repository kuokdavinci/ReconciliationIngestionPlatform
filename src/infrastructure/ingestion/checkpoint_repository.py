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
    SourceUnitStatus,
    SourceUnitSummary,
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

    @staticmethod
    def _unit_timeline_update(
        checkpoint: IngestionCheckpoint,
        unit_key: str,
        *,
        status: SourceUnitStatus,
        page: Optional[int] = None,
        label: Optional[str] = None,
        cursor_before: Optional[str] = None,
        cursor_after: Optional[str] = None,
        attempt_count: Optional[int] = None,
        last_error: Any = None,
        error_code: Any = None,
        retryable: Any = None,
        next_retry_at: Any = None,
        started_at: Any = None,
        completed_at: Any = None,
        clear_error: bool = False,
    ) -> list[dict[str, Any]]:
        entries = list(checkpoint.unit_timeline)
        index = next((i for i, item in enumerate(entries) if item.unit_key == unit_key), None)
        current = entries[index] if index is not None else SourceUnitSummary(unitKey=unit_key)
        updates: dict[str, Any] = {"status": status, "updated_at": datetime.now(UTC)}
        if page is not None:
            updates["page"] = page
        if label is not None:
            updates["label"] = label
        if cursor_before is not None:
            updates["cursor_before"] = cursor_before
        if cursor_after is not None:
            updates["cursor_after"] = cursor_after
        if attempt_count is not None:
            updates["attempt_count"] = attempt_count
        if clear_error:
            updates.update(
                last_error=None,
                error_code=None,
                retryable=None,
                next_retry_at=None,
            )
        else:
            updates.update(
                last_error=last_error,
                error_code=error_code,
                retryable=retryable,
                next_retry_at=next_retry_at,
            )
        if started_at is not None:
            updates["started_at"] = started_at
        updates["completed_at"] = completed_at
        current = current.model_copy(update=updates)
        if index is None:
            entries.append(current)
        else:
            entries[index] = current
        return [entry.model_dump(by_alias=True) for entry in entries]

    @staticmethod
    def _recovery_event_update(
        checkpoint: IngestionCheckpoint,
        *,
        unit_key: str,
        status: str,
        timestamp: Optional[datetime] = None,
        error_code: Optional[str] = None,
        message: Optional[str] = None,
        action: Optional[str] = None,
        actor: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> dict[str, Any]:
        event: dict[str, Any] = {
            "eventId": str(uuid4()),
            "unitKey": unit_key,
            "status": status,
            "timestamp": timestamp or datetime.now(UTC),
        }
        for key, value in (
            ("errorCode", error_code),
            ("message", message),
            ("action", action),
            ("actor", actor),
            ("reason", reason),
        ):
            if value is not None:
                event[key] = value
        return event

    async def find_by_stream(self, *, partner: str, fetch_config_id: str, source_type: str, stream_key: str, mode: IngestionMode = IngestionMode.SCHEDULED) -> Optional[IngestionCheckpoint]:
        return await self.find_one(self._stream_filter(partner=partner, fetch_config_id=fetch_config_id, source_type=source_type, stream_key=stream_key, mode=mode))

    async def find_by_streams(
        self,
        identities: list[dict[str, Any]],
    ) -> list[IngestionCheckpoint]:
        if not identities:
            return []
        filters = [
            {
                **self._stream_filter(
                    partner=identity["partner"],
                    fetch_config_id=identity["fetchConfigId"],
                    source_type=identity["sourceType"],
                    stream_key=identity.get("streamKey", ""),
                    mode=identity.get("mode", IngestionMode.SCHEDULED),
                ),
                **(
                    {}
                    if identity.get("streamKey")
                    else {"streamKey": {"$exists": True}}
                ),
            }
            for identity in identities
        ]
        return await self.find_many({"$or": filters})

    async def find_by_source_unit_key(
        self,
        source_unit_key: str,
    ) -> Optional[IngestionCheckpoint]:
        """Find the stream checkpoint that owns a source-unit identity."""
        return await self.find_one(
            {
                "$or": [
                    {"currentUnitKey": source_unit_key},
                    {"lastCompletedUnitKey": source_unit_key},
                    {"unitTimeline.unitKey": source_unit_key},
                ]
            }
        )

    async def prepare_manual_retry(
        self,
        checkpoint: IngestionCheckpoint,
        *,
        operator_id: str,
        reason: str,
    ) -> bool:
        if checkpoint.status != CheckpointStatus.FAILED:
            return False
        if not checkpoint.current_unit_key or checkpoint.retryable is not True:
            return False
        now = datetime.now(UTC)
        query = {
            **self._stream_filter(
                partner=checkpoint.partner,
                fetch_config_id=checkpoint.fetch_config_id,
                source_type=checkpoint.source_type,
                stream_key=checkpoint.stream_key,
                mode=checkpoint.mode,
            ),
            "currentUnitKey": checkpoint.current_unit_key,
            "status": CheckpointStatus.FAILED.value,
            "retryable": True,
        }
        update = {
            "$set": {
                "nextRetryAt": None,
                "updatedAt": now,
                "resolutionMetadata": {
                    "action": "RETRY",
                    "reason": reason,
                    "operatorId": operator_id,
                    "resolvedAt": now,
                },
                "unitTimeline": self._unit_timeline_update(
                    checkpoint,
                    checkpoint.current_unit_key,
                    status=SourceUnitStatus.FAILED,
                    attempt_count=checkpoint.attempt_count,
                    last_error=checkpoint.last_error,
                    error_code=checkpoint.error_code,
                    retryable=True,
                    next_retry_at=None,
                ),
            },
            "$push": {
                "recoveryEvents": self._recovery_event_update(
                    checkpoint,
                    unit_key=checkpoint.current_unit_key,
                    status="RETRY_REQUESTED",
                    timestamp=now,
                    action="RETRY",
                    actor=operator_id,
                    reason=reason,
                )
            },
        }
        result = await self.collection.update_one(query, update)
        return result.modified_count == 1

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

    async def update_source_context(
        self,
        checkpoint: IngestionCheckpoint,
        *,
        source_file_id: str | None = None,
        runtime_run_id: str | None = None,
    ) -> bool:
        """Attach the file identity after a source unit has been ingested."""
        fields: dict[str, Any] = {
            key: value
            for key, value in (
                ("sourceFileId", source_file_id),
                ("runtimeRunId", runtime_run_id),
            )
            if value is not None
        }
        if not fields:
            return False
        fields["updatedAt"] = datetime.now(UTC)
        result = await self.collection.update_one({"_id": str(checkpoint.id)}, {"$set": fields})
        return result.modified_count == 1

    async def claim_unit(self, *, partner: str, fetch_config_id: str, source_type: str, stream_key: str, unit_key: str, mode: IngestionMode = IngestionMode.SCHEDULED, cursor_before: Optional[str] = None, expected_previous_unit_key: Optional[str] = None, max_attempts: Optional[int] = None, config_version: Optional[str] = None, source_endpoint: Optional[str] = None, stream_metadata: Optional[dict[str, Any]] = None, runtime_run_id: Optional[str] = None, source_file_id: Optional[str] = None, attempt: Optional[int] = None, claim_timeout_seconds: int = 900) -> tuple[IngestionCheckpoint, bool]:
        identity = self._stream_filter(partner=partner, fetch_config_id=fetch_config_id, source_type=source_type, stream_key=stream_key, mode=mode)
        stream_metadata = dict(stream_metadata or {})
        if attempt is not None:
            stream_metadata.setdefault("attempt", max(1, int(attempt)))
        checkpoint, _ = await self.create_or_get(
            IngestionCheckpoint.model_validate(
                {
                    **identity,
                    "configVersion": config_version,
                    "sourceEndpoint": source_endpoint,
                    "runtimeRunId": runtime_run_id,
                    "sourceFileId": source_file_id,
                    "streamMetadata": stream_metadata,
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
        current_unit = next(
            (item for item in checkpoint.unit_timeline if item.unit_key == unit_key),
            None,
        )
        # Attempts are bounded per source unit, not across the whole stream.
        # A successful page must not consume the retry budget of the next page.
        next_attempt_count = (current_unit.attempt_count + 1) if current_unit else 1
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
                "runtimeRunId": runtime_run_id,
                "sourceFileId": source_file_id,
                "streamMetadata": stream_metadata,
                "unitTimeline": self._unit_timeline_update(
                    checkpoint,
                    unit_key,
                    status=SourceUnitStatus.PROCESSING,
                    page=(stream_metadata or {}).get("page"),
                    label=(stream_metadata or {}).get("label"),
                    cursor_before=cursor_before,
                    attempt_count=next_attempt_count,
                    started_at=now,
                    completed_at=None,
                    clear_error=True,
                ),
                "attemptCount": next_attempt_count,
            },
            "$push": {
                "recoveryEvents": self._recovery_event_update(
                    checkpoint,
                    unit_key=unit_key,
                    status=SourceUnitStatus.PROCESSING.value,
                    timestamp=now,
                )
            },
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
            stale_update = {
                "status": CheckpointStatus.BLOCKED.value,
                "retryable": False,
                "blockedAt": now,
                "blockedReason": "Maximum source-unit attempts exhausted.",
                "updatedAt": now,
            }
            if existing.current_unit_key:
                stale_update["unitTimeline"] = self._unit_timeline_update(
                    existing,
                    existing.current_unit_key,
                    status=SourceUnitStatus.BLOCKED,
                    last_error="Maximum source-unit attempts exhausted.",
                    error_code=existing.error_code,
                    retryable=False,
                    next_retry_at=None,
                )
            await self.collection.update_one(
                stale_query,
                {
                    "$set": stale_update
                },
            )
        return existing, False

    async def mark_failed(self, checkpoint: IngestionCheckpoint, *, unit_key: str, error: str, error_code: str = "source_unit_failed", retryable: bool = True, next_retry_at: Optional[datetime] = None, max_attempts: Optional[int] = None, error_metadata: Optional[dict[str, Any]] = None) -> bool:
        if max_attempts is not None and max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        blocked = not retryable or (max_attempts is not None and checkpoint.attempt_count >= max_attempts)
        now = datetime.now(UTC)
        query = {**self._stream_filter(partner=checkpoint.partner, fetch_config_id=checkpoint.fetch_config_id, source_type=checkpoint.source_type, stream_key=checkpoint.stream_key, mode=checkpoint.mode), "currentUnitKey": unit_key, "status": CheckpointStatus.PROCESSING.value, "claimId": checkpoint.claim_id}
        transition_status = SourceUnitStatus.BLOCKED if blocked else SourceUnitStatus.FAILED
        result = await self.collection.update_one(
            query,
            {
                "$set": {
                    "status": CheckpointStatus.BLOCKED.value if blocked else CheckpointStatus.FAILED.value,
                    "lastError": error,
                    "errorCode": error_code,
                    "retryable": retryable,
                    "nextRetryAt": None if blocked else next_retry_at,
                    "blockedAt": now if blocked else None,
                    "blockedReason": error if blocked else None,
                    "lastErrorMetadata": error_metadata or {},
                    "updatedAt": now,
                    "unitTimeline": self._unit_timeline_update(
                        checkpoint,
                        unit_key,
                        status=transition_status,
                        attempt_count=checkpoint.attempt_count,
                        last_error=error,
                        error_code=error_code,
                        retryable=retryable,
                        next_retry_at=None if blocked else next_retry_at,
                    ),
                },
                "$push": {
                    "recoveryEvents": self._recovery_event_update(
                        checkpoint,
                        unit_key=unit_key,
                        status=transition_status.value,
                        timestamp=now,
                        error_code=error_code,
                        message=error,
                    )
                },
            },
        )
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
                    "unitTimeline": self._unit_timeline_update(
                        checkpoint,
                        unit_key,
                        status=SourceUnitStatus.WAITING_REVIEW,
                        attempt_count=checkpoint.attempt_count,
                        last_error=reason,
                        error_code="configuration_approval_required",
                        retryable=None,
                        next_retry_at=None,
                    ),
                },
                "$push": {
                    "recoveryEvents": self._recovery_event_update(
                        checkpoint,
                        unit_key=unit_key,
                        status=SourceUnitStatus.WAITING_REVIEW.value,
                        timestamp=now,
                        error_code="configuration_approval_required",
                        message=reason,
                    )
                },
            },
        )
        return result.modified_count == 1

    async def resolve_blocked(self, checkpoint: IngestionCheckpoint, *, unit_key: str, action: str, reason: str, operator_id: str) -> bool:
        if action not in {"RETRY", "SKIP"}:
            raise ValueError("action must be RETRY or SKIP")
        query = {**self._stream_filter(partner=checkpoint.partner, fetch_config_id=checkpoint.fetch_config_id, source_type=checkpoint.source_type, stream_key=checkpoint.stream_key, mode=checkpoint.mode), "currentUnitKey": unit_key, "status": CheckpointStatus.BLOCKED.value}
        now = datetime.now(UTC)
        result = await self.collection.update_one(
            query,
            {
                "$set": {
                    "status": CheckpointStatus.DISCOVERED.value,
                    "retryable": True,
                    "nextRetryAt": None,
                    "blockedAt": None,
                    "blockedReason": None,
                    "resolutionMetadata": {
                        "action": action,
                        "reason": reason,
                        "operatorId": operator_id,
                        "resolvedAt": now,
                    },
                    "updatedAt": now,
                    "unitTimeline": self._unit_timeline_update(
                        checkpoint,
                        unit_key,
                        status=SourceUnitStatus.PENDING,
                        last_error=None,
                        error_code=None,
                        retryable=True,
                        next_retry_at=None,
                    ),
                },
                "$push": {
                    "recoveryEvents": self._recovery_event_update(
                        checkpoint,
                        unit_key=unit_key,
                        status="RESOLVED",
                        timestamp=now,
                        action=action,
                        actor=operator_id,
                        reason=reason,
                    )
                },
            },
        )
        return result.modified_count == 1

    async def mark_completed(self, checkpoint: IngestionCheckpoint, *, unit_key: str, cursor_after: Optional[str] = None, high_water_mark: Optional[dict[str, Any]] = None) -> bool:
        query = {**self._stream_filter(partner=checkpoint.partner, fetch_config_id=checkpoint.fetch_config_id, source_type=checkpoint.source_type, stream_key=checkpoint.stream_key, mode=checkpoint.mode), "currentUnitKey": unit_key, "status": CheckpointStatus.PROCESSING.value, "claimId": checkpoint.claim_id}
        now = datetime.now(UTC)
        skipped = (checkpoint.resolution_metadata or {}).get("action") == "SKIP"
        completion_status = SourceUnitStatus.SKIPPED if skipped else SourceUnitStatus.COMPLETED
        result = await self.collection.update_one(
            query,
            {
                "$set": {
                    "status": CheckpointStatus.COMPLETED.value,
                    "lastCompletedUnitKey": unit_key,
                    "cursorAfter": cursor_after,
                    "highWaterMark": high_water_mark,
                    "streamEnded": (high_water_mark or {}).get("hasMore") is False,
                    "lastError": None,
                    "errorCode": None,
                    "retryable": None,
                    "nextRetryAt": None,
                    "blockedAt": None,
                    "blockedReason": None,
                    "resolutionMetadata": {},
                    "completedAt": now,
                    "updatedAt": now,
                    "lastErrorMetadata": {},
                    "unitTimeline": self._unit_timeline_update(
                        checkpoint,
                        unit_key,
                        status=completion_status,
                        attempt_count=checkpoint.attempt_count,
                        cursor_after=cursor_after,
                        clear_error=True,
                        completed_at=now,
                    ),
                },
                "$push": {
                    "recoveryEvents": self._recovery_event_update(
                        checkpoint,
                        unit_key=unit_key,
                        status=completion_status.value,
                        timestamp=now,
                    )
                },
            },
        )
        return result.modified_count == 1

    async def advance(self, checkpoint: IngestionCheckpoint, *, unit_key: str) -> bool:
        query = {**self._stream_filter(partner=checkpoint.partner, fetch_config_id=checkpoint.fetch_config_id, source_type=checkpoint.source_type, stream_key=checkpoint.stream_key, mode=checkpoint.mode), "currentUnitKey": unit_key, "lastCompletedUnitKey": unit_key, "status": CheckpointStatus.COMPLETED.value}
        result = await self.collection.update_one(query, {"$set": {"status": CheckpointStatus.DISCOVERED.value, "currentUnitKey": None, "updatedAt": datetime.now(UTC)}})
        return result.modified_count == 1

    async def mark_stream_completed_after_review(
        self,
        checkpoint: IngestionCheckpoint,
        *,
        unit_key: str,
        cursor_after: Optional[str] = None,
        high_water_mark: Optional[dict[str, Any]] = None,
        completed_units: Optional[list[dict[str, Any]]] = None,
    ) -> bool:
        """Close a staged stream after its scope review has been reconciled."""

        query = {
            **self._stream_filter(
                partner=checkpoint.partner,
                fetch_config_id=checkpoint.fetch_config_id,
                source_type=checkpoint.source_type,
                stream_key=checkpoint.stream_key,
                mode=checkpoint.mode,
            ),
            "status": CheckpointStatus.DISCOVERED.value,
            "streamEnded": {"$ne": True},
        }
        now = datetime.now(UTC)
        timeline = {item.unit_key: item for item in checkpoint.unit_timeline}
        for payload in completed_units or [
            {"unitKey": unit_key, "cursorAfter": cursor_after}
        ]:
            completed_key = payload.get("unitKey") or payload.get("unit_key")
            if not isinstance(completed_key, str) or not completed_key:
                continue
            current = timeline.get(completed_key, SourceUnitSummary(unitKey=completed_key))
            updates: dict[str, Any] = {
                "status": SourceUnitStatus.COMPLETED,
                "last_error": None,
                "error_code": None,
                "retryable": None,
                "next_retry_at": None,
                "completed_at": now,
                "updated_at": now,
            }
            for payload_key, model_key in (
                ("page", "page"),
                ("label", "label"),
                ("cursorBefore", "cursor_before"),
                ("cursorAfter", "cursor_after"),
            ):
                if payload.get(payload_key) is not None:
                    updates[model_key] = payload[payload_key]
            timeline[completed_key] = current.model_copy(update=updates)
        update = {
            "$set": {
                "status": CheckpointStatus.DISCOVERED.value,
                "currentUnitKey": None,
                "lastCompletedUnitKey": unit_key,
                "cursorAfter": cursor_after,
                "highWaterMark": high_water_mark,
                "streamEnded": True,
                "lastError": None,
                "errorCode": None,
                "retryable": None,
                "nextRetryAt": None,
                "resolutionMetadata": {},
                "completedAt": now,
                "updatedAt": now,
                "lastErrorMetadata": {},
                "unitTimeline": [
                    item.model_dump(by_alias=True) for item in timeline.values()
                ],
            },
            "$push": {
                "recoveryEvents": self._recovery_event_update(
                    checkpoint,
                    unit_key=unit_key,
                    status=SourceUnitStatus.COMPLETED.value,
                    timestamp=now,
                    reason="Post-approval staged stream reconciliation completed.",
                )
            },
        }
        result = await self.collection.update_one(query, update)
        return result.modified_count == 1

    async def mark_stream_failed_after_review(
        self,
        checkpoint: IngestionCheckpoint,
        *,
        unit_key: str,
        error: str,
        error_code: str,
    ) -> bool:
        """Persist a post-approval replay failure without losing its unit owner."""
        query = {
            **self._stream_filter(
                partner=checkpoint.partner,
                fetch_config_id=checkpoint.fetch_config_id,
                source_type=checkpoint.source_type,
                stream_key=checkpoint.stream_key,
                mode=checkpoint.mode,
            ),
            "status": CheckpointStatus.DISCOVERED.value,
            "streamEnded": {"$ne": True},
        }
        now = datetime.now(UTC)
        update = {
            "$set": {
                "status": CheckpointStatus.FAILED.value,
                "currentUnitKey": unit_key,
                "lastError": error,
                "errorCode": error_code,
                "retryable": True,
                "nextRetryAt": None,
                "blockedAt": None,
                "blockedReason": None,
                "lastErrorMetadata": {},
                "updatedAt": now,
                "unitTimeline": self._unit_timeline_update(
                    checkpoint,
                    unit_key,
                    status=SourceUnitStatus.FAILED,
                    last_error=error,
                    error_code=error_code,
                    retryable=True,
                    next_retry_at=None,
                ),
            },
            "$push": {
                "recoveryEvents": self._recovery_event_update(
                    checkpoint,
                    unit_key=unit_key,
                    status=CheckpointStatus.FAILED.value,
                    timestamp=now,
                    error_code=error_code,
                    message=error,
                )
            },
        }
        result = await self.collection.update_one(query, update)
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
