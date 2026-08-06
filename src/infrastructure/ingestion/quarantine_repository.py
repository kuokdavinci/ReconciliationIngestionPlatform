"""MongoDB adapter for ingestion quarantine records."""

from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.domain.ingestion.quarantine import (
    IngestionQuarantineRecord,
    QuarantineStatus,
)
from src.infrastructure.persistence.mongo_repository import BaseRepository


class IngestionQuarantineRepository(BaseRepository[IngestionQuarantineRecord]):
    """Store rejected rows independently from canonical transactions."""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="ingestion_quarantine_record", db=db)
        self._set_model_class(IngestionQuarantineRecord)

    async def create_many(self, records: list[IngestionQuarantineRecord]) -> int:
        if not records:
            return 0
        await self.collection.insert_many([self._to_mongo(record) for record in records])
        return len(records)

    async def find_pending(self, *, partner: str | None = None, limit: int = 100) -> list[IngestionQuarantineRecord]:
        query: dict[str, Any] = {"status": QuarantineStatus.PENDING.value}
        if partner is not None:
            query["partner"] = partner
        cursor = self.collection.find(query).sort("createdAt", 1).limit(limit)
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
            update["resolutionMetadata"] = metadata
        return await self.update_one({"_id": record_id}, update)
