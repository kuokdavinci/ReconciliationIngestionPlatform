"""ReconciliationFile model and repository for tracking uploaded/imported files."""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError
from pydantic import BaseModel, ConfigDict, Field

from src.core.enums import FileType, ProcessingStatus, ReconciliationScopeType
from src.models.repository import BaseRepository


class ReconciliationFile(BaseModel):
    """Model for tracking uploaded/imported reconciliation files.

    The file_hash field is used for duplicate detection — a unique
    index on this field prevents re-ingestion of the same file.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: UUID = Field(default_factory=uuid4, alias="_id")
    partner: str
    file_name: str = Field(alias="fileName")
    file_hash: str = Field(alias="fileHash")
    file_type: FileType = Field(alias="fileType")
    reconciliation_date: datetime = Field(alias="reconciliationDate")
    processing_status: ProcessingStatus = Field(
        default=ProcessingStatus.PENDING, alias="processingStatus"
    )
    total_rows: int = Field(default=0, alias="totalRows")
    success_rows: int = Field(default=0, alias="successRows")
    failed_rows: int = Field(default=0, alias="failedRows")
    config_version: Optional[str] = Field(default=None, alias="configVersion")
    fetch_unit_key: Optional[str] = Field(default=None, alias="fetchUnitKey")
    fetch_unit_metadata: dict = Field(default_factory=dict, alias="fetchUnitMetadata")
    scope_type: ReconciliationScopeType = Field(
        default=ReconciliationScopeType.UNCONFIRMED,
        alias="scopeType",
    )
    scope_confidence: float = Field(default=0.0, alias="scopeConfidence")
    scope_reason: list[str] = Field(default_factory=list, alias="scopeReason")
    scope_signals: dict = Field(default_factory=dict, alias="scopeSignals")
    uploaded_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="uploadedAt"
    )
    created_by: str = Field(default="system", alias="createdBy")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="createdAt"
    )


class ReconciliationFileRepository(BaseRepository[ReconciliationFile]):
    """Repository for ReconciliationFile with domain-specific query methods."""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="reconciliation_file", db=db)
        self._set_model_class(ReconciliationFile)

    async def find_by_file_hash(self, file_hash: str) -> Optional[ReconciliationFile]:
        """Find a file by its SHA256 hash — used for duplicate detection."""
        return await self.find_one({"fileHash": file_hash})

    async def find_by_fetch_unit_key(
        self,
        fetch_unit_key: str,
    ) -> Optional[ReconciliationFile]:
        return await self.find_one({"fetchUnitKey": fetch_unit_key})

    async def create_or_get_by_file_hash(
        self, doc: ReconciliationFile
    ) -> tuple[ReconciliationFile, bool]:
        """Create a file record or return the existing canonical record.

        The unique file-hash index is the concurrency boundary. If two workers
        race on the same file, one insert wins and the loser resolves the
        duplicate by re-reading the canonical record.
        """
        try:
            created = await self.create(doc)
            return created, True
        except DuplicateKeyError:
            existing = await self.find_by_file_hash(doc.file_hash)
            if existing is None and doc.fetch_unit_key:
                existing = await self.find_by_fetch_unit_key(doc.fetch_unit_key)
            if existing is None:
                raise
            return existing, False

    async def find_by_partner_and_date(
        self, partner: str, reconciliation_date: datetime
    ) -> list[ReconciliationFile]:
        """Find all files for a partner on a specific reconciliation date."""
        return await self.find_many(
            {
                "partner": partner,
                "reconciliationDate": reconciliation_date,
            }
        )

    async def update_processing_stats(
        self,
        file_id: UUID,
        total: int,
        success: int,
        failed: int,
    ) -> bool:
        """Update processing statistics for a file."""
        return await self.update_one(
            {"_id": str(file_id)},
            {
                "totalRows": total,
                "successRows": success,
                "failedRows": failed,
            },
        )

    async def update_status(
        self, file_id: UUID, status: ProcessingStatus
    ) -> bool:
        """Update the processing status of a file."""
        return await self.update_one(
            {"_id": str(file_id)},
            {"processingStatus": status.value},
        )
