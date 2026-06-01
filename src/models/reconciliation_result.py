"""ReconciliationResult model and repository for storing matching output."""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from motor.motor_asyncio import AsyncIOMotorDatabase
from src.core.enums import ReconciliationStatus
from src.models.repository import BaseRepository


class ReconciliationResult(BaseModel):
    """ReconciliationResult model representing output of reconciliation matching.

    partner_record_id maps to DataContainer.id
    internal_record_id maps to InternalTransaction.id
    """

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: str = Field(alias="_id")  # unique ID, e.g. partnerTxnId or UUID
    partner_txn_id: str = Field(alias="partnerTxnId")
    internal_txn_id: Optional[str] = Field(default=None, alias="internalTxnId")

    partner_amount: Optional[Decimal] = Field(default=None, alias="partnerAmount")
    internal_amount: Optional[Decimal] = Field(default=None, alias="internalAmount")

    partner_status: Optional[str] = Field(default=None, alias="partnerStatus")
    internal_status: Optional[str] = Field(default=None, alias="internalStatus")

    reconciliation_status: ReconciliationStatus = Field(alias="reconciliationStatus")

    partner_record_id: Optional[str] = Field(default=None, alias="partnerRecordId")
    internal_record_id: Optional[str] = Field(default=None, alias="internalRecordId")

    created_at: datetime = Field(
        default_factory=datetime.utcnow, alias="createdAt"
    )


class ReconciliationResultRepository(BaseRepository[ReconciliationResult]):
    """Repository for ReconciliationResult with domain-specific queries."""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="reconciliation_result", db=db)
        self._set_model_class(ReconciliationResult)

    async def insert_many(self, docs: list[ReconciliationResult]) -> int:
        """Bulk insert multiple ReconciliationResult documents."""
        if not docs:
            return 0
        serialized = [self._to_mongo(doc) for doc in docs]
        result = await self.collection.insert_many(serialized)
        return len(result.inserted_ids)
