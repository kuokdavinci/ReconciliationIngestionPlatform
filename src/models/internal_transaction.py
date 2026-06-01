"""InternalTransaction model and repository for the core internal transactions."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
from motor.motor_asyncio import AsyncIOMotorDatabase
from src.core.enums import TransactionStatus
from src.models.repository import BaseRepository


class InternalTransaction(BaseModel):
    """Internal transaction model representing system records (Source of Truth).

    Monetary amounts use Decimal exclusively — floats are rejected.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: str = Field(alias="_id")  # internalTxnId
    partner: str  # MOMO, ZALOPAY, etc.
    partner_txn_id: str = Field(alias="partnerTxnId")  # reconciliation key
    amount: Decimal
    currency: str = "VND"
    status: TransactionStatus
    transaction_time: datetime = Field(alias="transactionTime")
    created_at: datetime = Field(
        default_factory=datetime.utcnow, alias="createdAt"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow, alias="updatedAt"
    )

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


class InternalTransactionRepository(BaseRepository[InternalTransaction]):
    """Repository for InternalTransaction with domain-specific queries."""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="internal_transaction", db=db)
        self._set_model_class(InternalTransaction)

    async def insert_many(self, docs: list[InternalTransaction]) -> int:
        """Bulk insert multiple InternalTransaction documents."""
        if not docs:
            return 0
        serialized = [self._to_mongo(doc) for doc in docs]
        result = await self.collection.insert_many(serialized)
        return len(result.inserted_ids)

    async def find_by_partner_and_date_range(
        self, partner: str, start: datetime, end: datetime
    ) -> list[InternalTransaction]:
        """Find internal transactions for a partner within a transaction time range."""
        return await self.find_many(
            {
                "partner": partner,
                "transactionTime": {
                    "$gte": start,
                    "$lte": end,
                },
            }
        )
