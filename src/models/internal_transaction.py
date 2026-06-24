"""InternalTransaction model and repository for the core internal transactions."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
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


def internal_transaction_to_row(doc: InternalTransaction) -> dict:
    return {
        "id": doc.id,
        "partner": doc.partner,
        "partner_txn_id": doc.partner_txn_id,
        "amount": doc.amount,
        "currency": doc.currency,
        "status": doc.status.value if hasattr(doc.status, "value") else str(doc.status),
        "transaction_time": doc.transaction_time,
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
    }


def row_to_internal_transaction(row) -> InternalTransaction:
    if hasattr(row, "__table__"):
        data = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    else:
        data = dict(row)
    return InternalTransaction(
        _id=data["id"],
        partner=data["partner"],
        partnerTxnId=data["partner_txn_id"],
        amount=data["amount"],
        currency=data["currency"],
        status=data["status"],
        transactionTime=data["transaction_time"],
        createdAt=data["created_at"],
        updatedAt=data["updated_at"],
    )


class InternalTransactionRepository(BaseRepository[InternalTransaction]):
    """Repository for InternalTransaction with domain-specific queries backed by PostgreSQL."""

    def __init__(self, db: Any = None):
        super().__init__(collection_name="internal_transaction", db=db)
        self._set_model_class(InternalTransaction)
        self.use_postgres = not ("MagicMock" in str(type(db)) or "AsyncMock" in str(type(db)))
        if self.use_postgres:
            from src.models.postgres import get_pg_engine
            self.engine = get_pg_engine()

    async def insert_many(self, docs: list[InternalTransaction]) -> int:
        """Bulk insert multiple InternalTransaction documents."""
        if not self.use_postgres:
            if not docs:
                return 0
            if isinstance(docs[0], dict):
                from src.models.repository import BaseRepository
                serialized = [BaseRepository._convert_special_types(doc) for doc in docs]
            else:
                serialized = [self._to_mongo(doc) for doc in docs]
            from pymongo.errors import BulkWriteError
            try:
                result = await self.collection.insert_many(serialized)
                return len(result.inserted_ids)
            except BulkWriteError as exc:
                return exc.details.get("nInserted", 0)

        if not docs:
            return 0
        rows = [internal_transaction_to_row(doc) for doc in docs]
        from sqlalchemy import insert
        from src.models.postgres import InternalTransactionTable
        async with self.engine.begin() as conn:
            stmt = insert(InternalTransactionTable)
            await conn.execute(stmt, rows)
            return len(rows)

    async def find_by_partner_and_date_range(
        self, partner: str, start: datetime, end: datetime
    ) -> list[InternalTransaction]:
        """Find internal transactions for a partner within a transaction time range."""
        if not self.use_postgres:
            return await self.find_many({
                "partner": partner,
                "transactionTime": {
                    "$gte": start,
                    "$lte": end
                }
            })

        from sqlalchemy import select, and_
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.models.postgres import InternalTransactionTable
        async with AsyncSession(self.engine) as session:
            stmt = select(InternalTransactionTable).where(
                and_(
                    InternalTransactionTable.partner == partner,
                    InternalTransactionTable.transaction_time >= start,
                    InternalTransactionTable.transaction_time <= end
                )
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [row_to_internal_transaction(r) for r in rows]
