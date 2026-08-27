"""MongoDB adapter for ingestion quarantine records."""

from datetime import UTC, datetime, timedelta
from typing import Any, overload

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from src.domain.ingestion.quarantine import (
    IngestionQuarantineRecord,
    QuarantineAction,
    QuarantineQuery,
    QuarantineRetentionPolicy,
    QuarantineResolutionEvent,
    QuarantineStatus,
    assert_quarantine_transition,
)
from src.config.settings import settings
from src.infrastructure.persistence.mongo_repository import BaseRepository


def _bounded_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Keep lifecycle metadata bounded and free of sensitive evidence."""
    forbidden = ("raw", "fingerprint", "password", "secret", "token", "credential")
    bounded: dict[str, Any] = {}
    for key, value in metadata.items():
        key_text = str(key)
        normalized = "".join(character for character in key_text.lower() if character.isalnum())
        if (
            any(token in normalized for token in forbidden)
            or normalized in {"error", "exception", "trace", "stacktrace", "traceback", "authorization"}
            or (normalized.startswith("error") and normalized != "errorcode")
            or normalized.startswith(("api", "auth"))
        ):
            continue
        if isinstance(value, str):
            bounded[key_text] = value[:512]
        elif isinstance(value, (int, float, bool)) or value is None:
            bounded[key_text] = value
    return bounded


def _bounded_limit(value: int, *, maximum: int = 200) -> int:
    return max(1, min(int(value), maximum))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class IngestionQuarantineRepository(BaseRepository[IngestionQuarantineRecord]):
    """Store rejected rows independently from canonical transactions."""

    def __init__(
        self,
        db: AsyncIOMotorDatabase,
        retention_policy: QuarantineRetentionPolicy | None = None,
    ):
        super().__init__(collection_name="ingestion_quarantine_record", db=db)
        self._set_model_class(IngestionQuarantineRecord)
        self.retention_policy = retention_policy or QuarantineRetentionPolicy()

    async def create_many(self, records: list[IngestionQuarantineRecord]) -> int:
        if not records:
            return 0
        expires_at = datetime.now(UTC) + timedelta(
            days=settings.ingestion_quarantine_retention_days
        )
        documents = [
            self._to_mongo(
                record.model_copy(update={"expires_at": expires_at})
                if record.expires_at is None
                else record.model_copy(
                    update={
                        "expires_at": min(
                            _as_utc(record.expires_at),
                            expires_at,
                        )
                    }
                )
            )
            for record in records
        ]
        await self.collection.insert_many(documents)
        return len(records)

    async def rebind_source_file(self, source_file_id: str, target_source_file_id: str) -> int:
        """Move quarantine lineage to the logical file kept for a staged stream."""
        result = await self.collection.update_many(
            {"sourceFileId": source_file_id},
            {"$set": {"sourceFileId": target_source_file_id}},
        )
        return int(getattr(result, "modified_count", 0) or 0)

    async def find_by_id(self, record_id: str) -> IngestionQuarantineRecord | None:
        return await self.find_one({"_id": record_id})

    @staticmethod
    def _event_payload(event: QuarantineResolutionEvent) -> dict[str, Any]:
        return BaseRepository._convert_special_types(
            event.model_dump(by_alias=True)
        )

    async def claim(
        self,
        record_id: str,
        operator_id: str,
        lease_seconds: int = 900,
    ) -> IngestionQuarantineRecord | None:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")
        current = await self.find_by_id(record_id)
        if current is None or current.status is not QuarantineStatus.PENDING:
            return None

        now = datetime.now(UTC)
        claim_expires_at = now + timedelta(seconds=lease_seconds)
        event = QuarantineResolutionEvent(
            fromStatus=QuarantineStatus.PENDING,
            toStatus=QuarantineStatus.REPROCESSING,
            action=QuarantineAction.REPROCESS,
            actor=operator_id,
            reason="Quarantine record claimed for processing.",
            attempt=current.attempt_count + 1,
            metadata={"leaseSeconds": lease_seconds},
        )
        raw = await self.collection.find_one_and_update(
            {"_id": record_id, "status": QuarantineStatus.PENDING.value},
            {
                "$set": {
                    "status": QuarantineStatus.REPROCESSING.value,
                    "claimedBy": operator_id,
                    "claimedAt": now,
                    "claimExpiresAt": claim_expires_at,
                    "lastAttemptError": None,
                    "updatedAt": now,
                },
                "$inc": {"attemptCount": 1},
                "$push": {
                    "resolutionHistory": self._event_payload(event),
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        if raw is None:
            return None
        return self._from_mongo(raw)

    async def find_pending(self, *, partner: str | None = None, limit: int = 100) -> list[IngestionQuarantineRecord]:
        query: dict[str, Any] = {"status": QuarantineStatus.PENDING.value}
        if partner is not None:
            query["partner"] = partner
        cursor = self.collection.find(query).sort("createdAt", 1).limit(_bounded_limit(limit))
        records = []
        async for raw in cursor:
            records.append(self._from_mongo(raw))
        return records

    async def find_blockers(self, source_unit_key: str) -> list[IngestionQuarantineRecord]:
        """Return active quarantine records associated with one source unit."""
        cursor = self.collection.find(
            {
                "sourceUnitKey": source_unit_key,
                "status": {
                    "$in": [
                        QuarantineStatus.PENDING.value,
                        QuarantineStatus.REPROCESSING.value,
                    ]
                },
            }
        ).sort([("createdAt", 1), ("_id", 1)])
        return [self._from_mongo(raw) async for raw in cursor]

    async def has_unresolved_blockers(self, source_unit_key: str) -> bool:
        """Check only active conflicting duplicates for a source-unit hold."""
        raw = await self.collection.find_one(
            {
                "sourceUnitKey": source_unit_key,
                "status": {
                    "$in": [
                        QuarantineStatus.PENDING.value,
                        QuarantineStatus.REPROCESSING.value,
                    ]
                },
                "errors.errorCode": "CONFLICTING_DUPLICATE",
            },
            projection={"_id": 1},
        )
        return raw is not None

    async def purge_expired(self, now: datetime | None = None, limit: int = 100) -> int:
        """Delete only bounded, expired terminal evidence records."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        now = now or datetime.now(UTC)
        cursor = self.collection.find(
            {
                "status": {
                    "$in": [
                        QuarantineStatus.RESOLVED.value,
                        QuarantineStatus.REJECTED.value,
                    ]
                },
                "retentionUntil": {"$lte": now},
            },
            projection={"_id": 1},
        ).sort([("retentionUntil", 1), ("_id", 1)]).limit(limit)
        removed = 0
        async for raw in cursor:
            result = await self.collection.delete_one({"_id": raw["_id"]})
            removed += int(result.deleted_count or 0)
        return removed

    @overload
    async def find_many(
        self,
        query: dict[Any, Any],
    ) -> list[IngestionQuarantineRecord]: ...

    @overload
    async def find_many(
        self,
        query: QuarantineQuery,
    ) -> tuple[list[IngestionQuarantineRecord], str | None]: ...

    async def find_many(
        self,
        query: dict[Any, Any] | QuarantineQuery,
    ) -> list[IngestionQuarantineRecord] | tuple[list[IngestionQuarantineRecord], str | None]:
        if isinstance(query, dict):
            return await super().find_many(query)
        filters: dict[str, Any] = {}
        if query.partner is not None:
            filters["partner"] = query.partner
        if query.status is not None:
            filters["status"] = query.status.value
        if query.phase is not None:
            filters["phase"] = query.phase.value
        if query.error_code is not None:
            filters["errors.errorCode"] = query.error_code
        if query.source_file_id is not None:
            filters["sourceFileId"] = query.source_file_id
        if query.source_unit_key is not None:
            filters["sourceUnitKey"] = query.source_unit_key
        if query.from_date is not None or query.to_date is not None:
            date_filter: dict[str, datetime] = {}
            if query.from_date is not None:
                date_filter["$gte"] = query.from_date
            if query.to_date is not None:
                date_filter["$lt"] = query.to_date
            filters["createdAt"] = date_filter
        if query.cursor is not None:
            cursor_date_text, cursor_id = query.cursor.split("|", maxsplit=1)
            cursor_date = datetime.fromisoformat(cursor_date_text)
            filters["$or"] = [
                {"createdAt": {"$gt": cursor_date}},
                {"createdAt": cursor_date, "_id": {"$gt": cursor_id}},
            ]

        cursor = self.collection.find(filters).sort(
            [("createdAt", 1), ("_id", 1)]
        ).limit(query.limit)
        records = [self._from_mongo(raw) async for raw in cursor]
        next_cursor = None
        if records:
            last = records[-1]
            next_cursor = f"{last.created_at.isoformat()}|{last.id}"
        return records, next_cursor

    async def mark_status(
        self,
        record_id: str,
        status: QuarantineStatus,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        update: dict[str, Any] = {
            "status": status.value,
            "updatedAt": datetime.now(UTC),
        }
        if metadata is not None:
            update["resolutionMetadata"] = _bounded_metadata(metadata)
        return await self.update_one({"_id": record_id}, update)

    async def release_for_retry(
        self,
        record_id: str,
        operator_id: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        current = await self.find_by_id(record_id)
        if (
            current is None
            or current.status is not QuarantineStatus.REPROCESSING
            or current.claimed_by != operator_id
        ):
            return False
        assert_quarantine_transition(
            QuarantineStatus.REPROCESSING,
            QuarantineStatus.PENDING,
        )
        now = datetime.now(UTC)
        event = QuarantineResolutionEvent(
            fromStatus=QuarantineStatus.REPROCESSING,
            toStatus=QuarantineStatus.PENDING,
            action=QuarantineAction.REPROCESS,
            actor=operator_id,
            reason=reason,
            attempt=current.attempt_count,
            metadata=metadata or {},
        )
        result = await self.collection.update_one(
            {
                "_id": record_id,
                "status": QuarantineStatus.REPROCESSING.value,
                "claimedBy": operator_id,
            },
            {
                "$set": {
                    "status": QuarantineStatus.PENDING.value,
                    "claimedBy": None,
                    "claimedAt": None,
                    "claimExpiresAt": None,
                    "lastAttemptError": reason,
                    "updatedAt": now,
                },
                "$push": {
                    "resolutionHistory": self._event_payload(event),
                },
            },
        )
        return result.modified_count == 1

    async def resolve(
        self,
        record_id: str,
        target: QuarantineStatus,
        operator_id: str,
        action: QuarantineAction,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        assert_quarantine_transition(QuarantineStatus.REPROCESSING, target)
        current = await self.find_by_id(record_id)
        if (
            current is None
            or current.status is not QuarantineStatus.REPROCESSING
            or current.claimed_by != operator_id
        ):
            return False
        now = datetime.now(UTC)
        retention_until = now + timedelta(days=self.retention_policy.days_for(target))
        event = QuarantineResolutionEvent(
            fromStatus=QuarantineStatus.REPROCESSING,
            toStatus=target,
            action=action,
            actor=operator_id,
            reason=reason,
            attempt=current.attempt_count,
            metadata=metadata or {},
        )
        result = await self.collection.update_one(
            {
                "_id": record_id,
                "status": QuarantineStatus.REPROCESSING.value,
                "claimedBy": operator_id,
            },
            {
                "$set": {
                    "status": target.value,
                    "claimedBy": None,
                    "claimedAt": None,
                    "claimExpiresAt": None,
                    "lastAttemptError": None,
                    "resolutionMetadata": metadata or {},
                    "retentionUntil": retention_until,
                    "updatedAt": now,
                },
                "$push": {
                    "resolutionHistory": self._event_payload(event),
                },
            },
        )
        return result.modified_count == 1
