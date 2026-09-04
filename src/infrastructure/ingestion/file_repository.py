"""MongoDB adapter for ingestion file claims."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from src.core.enums import ProcessingStatus
from src.domain.ingestion.models import ReconciliationFile
from src.infrastructure.persistence.mongo_repository import BaseRepository


class ReconciliationFileRepository(BaseRepository[ReconciliationFile]):
    """Persistence adapter for ``reconciliation_file`` claims."""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="reconciliation_file", db=db)
        self._set_model_class(ReconciliationFile)

    async def find_by_file_hash(
        self,
        partner: str,
        file_hash: str,
    ) -> Optional[ReconciliationFile]:
        return await self.find_one({"partner": partner, "fileHash": file_hash})

    async def reclaim_failed_by_file_hash(
        self,
        partner: str,
        file_hash: str,
    ) -> Optional[ReconciliationFile]:
        raw = await self.collection.find_one_and_update(
            {
                "partner": partner,
                "fileHash": file_hash,
                "processingStatus": ProcessingStatus.FAILED.value,
            },
            {
                "$set": {
                    "processingStatus": ProcessingStatus.PROCESSING.value,
                    "totalRows": 0,
                    "successRows": 0,
                    "failedRows": 0,
                    "duplicateRows": 0,
                    "stageSummary": {},
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return self._from_mongo(raw) if raw is not None else None

    async def find_by_fetch_unit_key(
        self,
        fetch_unit_key: str,
    ) -> Optional[ReconciliationFile]:
        return await self.find_one(
            {
                "$or": [
                    {"fetchUnitKey": fetch_unit_key},
                    {"fetchUnitMetadata.sourceUnitKey": fetch_unit_key},
                    {"fetchUnitMetadata.sourceUnitKeys": fetch_unit_key},
                ]
            }
        )

    async def find_completed_by_raw_stage_key(
        self,
        raw_stage_key: str,
    ) -> Optional[ReconciliationFile]:
        return await self.find_one(
            {
                "fetchUnitMetadata.rawStageKey": raw_stage_key,
                "processingStatus": ProcessingStatus.COMPLETED.value,
            }
        )

    async def create_or_get_by_file_hash(
        self, doc: ReconciliationFile
    ) -> tuple[ReconciliationFile, bool]:
        try:
            created = await self.create(doc)
            return created, True
        except DuplicateKeyError:
            existing = await self.find_by_file_hash(doc.partner, doc.file_hash)
            if existing is None and doc.fetch_unit_key:
                existing = await self.find_by_fetch_unit_key(doc.fetch_unit_key)
            if existing is None:
                raise
            return existing, False

    async def find_by_partner_and_date(
        self, partner: str, reconciliation_date: datetime
    ) -> list[ReconciliationFile]:
        return await self.find_many(
            {
                "partner": partner,
                "reconciliationDate": reconciliation_date,
            }
        )

    async def read_row(self, source_file_id: str, row_number: int) -> Any | None:
        """Read one row from the retained source path for a quarantine replay."""
        source_file = await self.find_one({"_id": source_file_id})
        if source_file is None:
            return None
        source_path = source_file.source_file_path or (
            source_file.fetch_unit_metadata or {}
        ).get("localPath")
        if not source_path or not Path(source_path).is_file():
            return None

        from src.infrastructure.ingestion.source_row_reader import read_authoritative_row

        return read_authoritative_row(source_path, row_number)

    async def update_processing_stats(
        self,
        file_id: UUID,
        total: int,
        success: int,
        failed: int,
        duplicate: int = 0,
    ) -> bool:
        return await self.update_one(
            {"_id": str(file_id)},
            {
                "totalRows": total,
                "successRows": success,
                "failedRows": failed,
                "duplicateRows": duplicate,
            },
        )

    async def update_status(self, file_id: UUID, status: ProcessingStatus) -> bool:
        return await self.update_one(
            {"_id": str(file_id)},
            {"processingStatus": status.value},
        )

    async def update_stage_summary(
        self,
        file_id: UUID,
        summary: dict,
    ) -> bool:
        return await self.update_one(
            {"_id": str(file_id)},
            {"stageSummary": summary, "updatedAt": datetime.now(UTC)},
        )
