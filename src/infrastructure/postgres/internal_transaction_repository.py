"""PostgreSQL adapter for internal source-of-truth transactions."""

from datetime import datetime, timezone
from typing import Any
from src.domain.internal_transaction.models import InternalTransaction


def internal_transaction_to_row(doc: InternalTransaction) -> dict:
    def as_utc_naive(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    return {
        "id": doc.id,
        "partner": doc.partner,
        "partner_txn_id": doc.partner_txn_id,
        "amount": doc.amount,
        "currency": doc.currency,
        "status": doc.status.value if hasattr(doc.status, "value") else str(doc.status),
        "transaction_time": as_utc_naive(doc.transaction_time),
        "created_at": as_utc_naive(doc.created_at),
        "updated_at": as_utc_naive(doc.updated_at),
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


class InternalTransactionRepository:
    """PostgreSQL repository for internal source-of-truth transactions."""

    def __init__(self, db: Any = None, engine: Any = None):
        del db
        if engine is None:
            from src.infrastructure.persistence.postgres_connection import get_pg_engine

            engine = get_pg_engine()
        self.engine = engine

    async def insert_many(self, docs: list[InternalTransaction]) -> int:
        """Bulk insert multiple InternalTransaction documents."""
        if not docs:
            return 0
        rows = [internal_transaction_to_row(doc) for doc in docs]
        from sqlalchemy import insert
        from src.infrastructure.persistence.postgres_schema import InternalTransactionTable
        async with self.engine.begin() as conn:
            stmt = insert(InternalTransactionTable)
            await conn.execute(stmt, rows)
            return len(rows)

    async def find_existing_partner_txn_ids(
        self, partner: str, partner_txn_ids: list[str]
    ) -> set[str]:
        """Return source keys already stored for a partner."""
        if not partner_txn_ids:
            return set()
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import InternalTransactionTable

        async with AsyncSession(self.engine) as session:
            result = await session.execute(
                select(InternalTransactionTable.partner_txn_id).where(
                    InternalTransactionTable.partner == partner,
                    InternalTransactionTable.partner_txn_id.in_(partner_txn_ids),
                )
            )
            return set(result.scalars().all())

    async def delete_by_partner_and_txn_id(self, partner: str, partner_txn_id: str) -> int:
        """Delete one source transaction and return the number of deleted rows."""
        from sqlalchemy import delete
        from src.infrastructure.persistence.postgres_schema import InternalTransactionTable

        async with self.engine.begin() as conn:
            result = await conn.execute(
                delete(InternalTransactionTable).where(
                    InternalTransactionTable.partner == partner,
                    InternalTransactionTable.partner_txn_id == partner_txn_id,
                )
            )
            return int(result.rowcount or 0)

    async def delete_by_partner(self, partner: str) -> int:
        """Delete all source transactions for a partner."""
        from sqlalchemy import delete
        from src.infrastructure.persistence.postgres_schema import InternalTransactionTable

        async with self.engine.begin() as conn:
            result = await conn.execute(
                delete(InternalTransactionTable).where(
                    InternalTransactionTable.partner == partner,
                )
            )
            return int(result.rowcount or 0)

    async def find_by_partner_and_date_range(
        self, partner: str, start: datetime, end: datetime
    ) -> list[InternalTransaction]:
        """Find internal transactions for a partner within a transaction time range."""
        if start.tzinfo is not None:
            start = start.replace(tzinfo=None)
        if end.tzinfo is not None:
            end = end.replace(tzinfo=None)
        from sqlalchemy import select, and_
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import InternalTransactionTable
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

    async def count_by_partner_and_date_range(
        self,
        partner: str,
        start: datetime,
        end: datetime,
    ) -> int:
        from sqlalchemy import and_, func, select
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import InternalTransactionTable

        if start.tzinfo is not None:
            start = start.replace(tzinfo=None)
        if end.tzinfo is not None:
            end = end.replace(tzinfo=None)
        async with AsyncSession(self.engine) as session:
            result = await session.execute(
                select(func.count())
                .select_from(InternalTransactionTable)
                .where(
                    and_(
                        InternalTransactionTable.partner == partner,
                        InternalTransactionTable.transaction_time >= start,
                        InternalTransactionTable.transaction_time <= end,
                    )
                )
            )
            return int(result.scalar() or 0)
