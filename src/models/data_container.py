"""DataContainer and PartnerData models for canonical normalized transaction storage."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID, uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from src.models.repository import BaseRepository


class PartnerData(BaseModel):
    """Raw partner data as a nested object (not a JSON string).

    Represents the original partner transaction before normalization.
    Monetary amounts use Decimal exclusively — floats are rejected to
    prevent floating-point precision errors in financial calculations.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: str = Field(alias="_id")
    trace: Optional[str] = None
    status: str
    amount: Decimal
    currency: str
    trans_date: Optional[datetime] = Field(default=None, alias="transDate")
    extra: dict[str, Any] = {}

    @field_validator("amount", mode="before")
    @classmethod
    def reject_float(cls, v: Any) -> Any:
        """Reject float values for amount — must be Decimal, int, or str."""
        if isinstance(v, float):
            raise ValueError(
                "amount must be Decimal, int, or str — float is not allowed "
                "for monetary values to avoid precision errors"
            )
        return v


class DataContainer(BaseModel):
    """Canonical normalized transaction storage.

    Each record represents one normalized transaction with full audit trail.
    partner_data is a nested PartnerData object (not a JSON string) for
    easier querying and indexing.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: UUID = Field(default_factory=uuid4, alias="_id")
    request_id: UUID = Field(default_factory=uuid4, alias="requestId")
    identify: str
    workflow_type: str = Field(alias="workflowType")
    reconciliation_date: datetime = Field(alias="reconciliationDate")
    operation_status: str = Field(default="IN_PROGRESS", alias="operationStatus")
    reconciliation_status: str = Field(default="", alias="reconciliationStatus")
    connector_data: str = Field(default="", alias="connectorData")
    extra_data: str = Field(default="", alias="extraData")
    source_file_id: UUID = Field(alias="sourceFileId")
    partner_data: PartnerData = Field(alias="partnerData")
    created_by: str = Field(default="system", alias="createdBy")
    created_date: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="createdDate"
    )
    last_modified_by: str = Field(default="system", alias="lastModifiedBy")
    last_modified_date: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        alias="lastModifiedDate",
    )


class DataContainerRepository(BaseRepository[DataContainer]):
    """Repository for DataContainer with domain-specific query methods."""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="data_container", db=db)
        self._set_model_class(DataContainer)

    async def insert_many(self, docs: list[DataContainer | dict], ordered: bool = True) -> int:
        """Bulk insert multiple DataContainer documents.

        Uses collection.insert_many for efficient batch insertion.
        Documents are serialized with UUID-to-string conversion.

        Args:
            docs: List of DataContainer or dict objects to insert.
            ordered: If True, insert documents serially; if False, perform parallel/unordered inserts.

        Returns:
            Number of documents inserted.
        """
        if not docs:
            return 0
            
        if isinstance(docs[0], dict):
            from src.models.repository import BaseRepository
            serialized = [BaseRepository._convert_special_types(doc) for doc in docs]
        else:
            serialized = [self._to_mongo(doc) for doc in docs]
            
        from pymongo.errors import BulkWriteError
        try:
            result = await self.collection.insert_many(serialized, ordered=ordered)
            return len(result.inserted_ids)
        except BulkWriteError as exc:
            return exc.details.get("nInserted", 0)


    async def find_by_trace(
        self, identify: str, trace: str
    ) -> Optional[DataContainer]:
        """Find a transaction by partner identifier and trace."""
        return await self.find_one(
            {"identify": identify, "partnerData.trace": trace}
        )

    async def find_by_source_file(
        self, source_file_id: UUID
    ) -> list[DataContainer]:
        """Find all transactions from a specific source file."""
        return await self.find_many({"sourceFileId": str(source_file_id)})

    async def find_by_date_range(
        self, identify: str, start: datetime, end: datetime
    ) -> list[DataContainer]:
        """Find all transactions for a partner within a date range."""
        return await self.find_many(
            {
                "identify": identify,
                "reconciliationDate": {
                    "$gte": start,
                    "$lte": end,
                },
            }
        )

    async def find_by_duplicate_key(
        self, identify: str, reconciliation_date: datetime, trace: str
    ) -> Optional[DataContainer]:
        """Find a transaction by its duplicate detection key.

        Queries by identify + reconciliationDate + partnerData.trace — the
        composite key used to detect duplicate transactions during ingestion.
        Uses indexed fields (idx_identify_date + idx_trace) for efficiency.

        Args:
            identify: Partner identifier.
            reconciliation_date: Date of the reconciliation file.
            trace: Partner transaction trace identifier.

        Returns:
            DataContainer if a matching transaction exists, None otherwise.
        """
        return await self.find_one({
            "identify": identify,
            "reconciliationDate": reconciliation_date,
            "partnerData.trace": trace,
        })
