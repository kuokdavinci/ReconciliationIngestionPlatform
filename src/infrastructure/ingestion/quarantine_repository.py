"""MongoDB adapter for ingestion quarantine records."""

from datetime import UTC, datetime, timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from src.domain.ingestion.quarantine import (
    IngestionQuarantineRecord,
    QuarantineStatus,
    QuarantineTransitionResult,
    QuarantineTransitionStatus,
)
from src.config.settings import settings
from src.infrastructure.persistence.mongo_repository import BaseRepository


class IngestionQuarantineRepository(BaseRepository[IngestionQuarantineRecord]):
    """Store rejected rows independently from canonical transactions."""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="ingestion_quarantine_record", db=db)
        self._set_model_class(IngestionQuarantineRecord)

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

    async def find_by_id(self, record_id: str) -> IngestionQuarantineRecord | None:
        return await self.find_one({"_id": record_id})

    async def list_records(
        self,
        *,
        partner: str | None = None,
        status: QuarantineStatus | None = None,
        limit: int = 100,
    ) -> list[IngestionQuarantineRecord]:
        query: dict[str, Any] = {}
        if partner is not None:
            query["partner"] = partner
        if status is not None:
            query["status"] = status.value
        cursor = self.collection.find(query).sort("createdAt", 1).limit(_bounded_limit(limit))
        records = []
        async for raw in cursor:
            records.append(self._from_mongo(raw))
        return records

    async def transition(
        self,
        record_id: str,
        *,
        expected_status: QuarantineStatus,
        new_status: QuarantineStatus,
        metadata: dict[str, Any] | None = None,
        action_id: str,
    ) -> QuarantineTransitionResult:
        if not action_id or len(action_id) > 128:
            raise ValueError("action_id must be between 1 and 128 characters")
        now = datetime.now(UTC)
        update: dict[str, Any] = {
            "status": new_status.value,
            "updatedAt": now,
            "lastActionId": action_id,
        }
        if metadata is not None:
            update["resolutionMetadata"] = _bounded_metadata(metadata)
        if new_status is QuarantineStatus.REPROCESSING:
            actor = (metadata or {}).get("actor")
            if actor:
                update["claimedBy"] = str(actor)[:128]
                update["claimedAt"] = now

        raw = await self.collection.find_one_and_update(
            {
                "_id": record_id,
                "status": expected_status.value,
                "lastActionId": {"$ne": action_id},
            },
            {"$set": update},
            return_document=ReturnDocument.AFTER,
        )
        if raw is not None:
            return QuarantineTransitionResult(
                QuarantineTransitionStatus.APPLIED,
                self._from_mongo(raw),
            )

        current = await self.find_by_id(record_id)
        if current is None:
            return QuarantineTransitionResult(QuarantineTransitionStatus.NOT_FOUND)
        if current.last_action_id == action_id:
            return QuarantineTransitionResult(QuarantineTransitionStatus.REPLAYED, current)
        return QuarantineTransitionResult(QuarantineTransitionStatus.CONFLICT, current)

    async def find_pending(self, *, partner: str | None = None, limit: int = 100) -> list[IngestionQuarantineRecord]:
        query: dict[str, Any] = {"status": QuarantineStatus.PENDING.value}
        if partner is not None:
            query["partner"] = partner
        cursor = self.collection.find(query).sort("createdAt", 1).limit(_bounded_limit(limit))
        records = []
        async for raw in cursor:
            records.append(self._from_mongo(raw))
        return records

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


def _bounded_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Keep lifecycle metadata bounded and free of sensitive evidence."""
    forbidden = ("raw", "fingerprint", "password", "secret", "token", "credential")
    bounded: dict[str, Any] = {}
    for key, value in metadata.items():
        key_text = str(key)
        key_lower = key_text.lower()
        normalized = "".join(character for character in key_lower if character.isalnum())
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
