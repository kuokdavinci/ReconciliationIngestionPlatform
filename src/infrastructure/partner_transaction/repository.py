"""PostgreSQL repository for canonical partner transactions."""

from datetime import datetime
import json
from typing import Any, Optional
from uuid import UUID

from src.core.types import BatchInsertResult
from src.domain.partner_transaction.models import (
    DataContainer,
    FastDataContainer,
)
from src.infrastructure.partner_transaction.mappers import (
    data_container_to_row,
    document_to_data_container,
    row_to_data_container,
)


_PARTNER_TRANSACTION_COLUMNS = (
    "id", "request_id", "identify", "workflow_type", "reconciliation_date",
    "operation_status", "reconciliation_status", "connector_data", "extra_data",
    "source_file_id", "ingestion_key", "partner_id", "partner_trace", "partner_status",
    "partner_amount", "partner_currency", "partner_trans_date", "partner_metadata",
    "created_by", "created_date", "last_modified_by", "last_modified_date",
)

_PARTNER_TRANSACTION_COLUMN_SQL = ", ".join(_PARTNER_TRANSACTION_COLUMNS)


def _row_to_copy_tuple(row: dict) -> tuple:
    return (
        *(row[column] for column in _PARTNER_TRANSACTION_COLUMNS[:16]),
        row["partner_trans_date"],
        json.dumps(row["partner_metadata"])
        if isinstance(row["partner_metadata"], (dict, list))
        else row["partner_metadata"],
        *(row[column] for column in _PARTNER_TRANSACTION_COLUMNS[18:]),
    )


class DataContainerRepository:
    """PostgreSQL repository for canonical partner transactions."""

    def __init__(self, db: Any = None, engine: Any = None):
        del db  # Retained in the signature for existing dependency wiring.
        if engine is None:
            from src.infrastructure.persistence.postgres_connection import get_pg_engine

            engine = get_pg_engine()
        self.engine = engine

    async def copy_records(self, docs: list[DataContainer]) -> int:
        """Compatibility wrapper that preserves conflict-safe insertion."""
        if not docs:
            return 0
        rows = [data_container_to_row(doc) for doc in docs]
        return await self._insert_rows_conflict_safe(rows)

    async def _insert_rows_conflict_safe(self, rows: list[dict]) -> int:
        """Bulk insert rows with COPY while preserving the idempotency key."""
        tuples = [_row_to_copy_tuple(row) for row in rows]
        stage_table = "partner_transaction_stage"
        create_stage_sql = (
            f"CREATE TEMP TABLE {stage_table} "
            f"(LIKE partner_transaction INCLUDING DEFAULTS) ON COMMIT DROP"
        )
        insert_sql = f"""
            INSERT INTO partner_transaction ({_PARTNER_TRANSACTION_COLUMN_SQL})
            SELECT {_PARTNER_TRANSACTION_COLUMN_SQL}
            FROM {stage_table}
            ON CONFLICT (identify, ingestion_key) DO NOTHING
        """

        async with self.engine.begin() as conn:
            # Start the SQLAlchemy-managed transaction before using the raw
            # asyncpg connection. Otherwise PostgreSQL may auto-commit the
            # CREATE TEMP TABLE and immediately apply ON COMMIT DROP.
            from sqlalchemy import text
            await conn.execute(text(create_stage_sql))
            raw_conn = await conn.get_raw_connection()
            asyncpg_conn = raw_conn.driver_connection
            await asyncpg_conn.copy_records_to_table(
                stage_table,
                columns=_PARTNER_TRANSACTION_COLUMNS,
                records=tuples,
            )
            status = await asyncpg_conn.execute(insert_sql)

        # asyncpg returns an INSERT command tag such as "INSERT 0 19999".
        return int(status.rsplit(" ", 1)[-1])

    async def insert_many(
        self,
        docs: list[DataContainer | FastDataContainer | dict],
        ordered: bool = True,
        detailed: bool = False,
    ) -> int | BatchInsertResult:
        if not docs:
            return BatchInsertResult(inserted=0) if detailed else 0

        model_docs: list[DataContainer | FastDataContainer] = []
        for doc in docs:
            if isinstance(doc, dict):
                model_docs.append(document_to_data_container(doc))
            else:
                model_docs.append(doc)

        rows = [data_container_to_row(doc) for doc in model_docs]
        inserted = await self._insert_rows_conflict_safe(rows)

        duplicates = max(len(rows) - inserted, 0)
        if detailed:
            return BatchInsertResult(inserted=inserted, duplicates=duplicates)
        return inserted

    async def find_by_trace(self, identify: str, trace: str) -> Optional[DataContainer]:
        from sqlalchemy import select, and_
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable
        async with AsyncSession(self.engine) as session:
            stmt = select(PartnerTransactionTable).where(
                and_(PartnerTransactionTable.identify == identify, PartnerTransactionTable.partner_trace == trace)
            )
            result = await session.execute(stmt)
            row = result.scalars().first()
            return row_to_data_container(row) if row else None

    async def find_by_ingestion_key(
        self,
        identify: str,
        ingestion_key: str,
    ) -> Optional[DataContainer]:
        from sqlalchemy import and_, select
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable

        async with AsyncSession(self.engine) as session:
            stmt = select(PartnerTransactionTable).where(
                and_(
                    PartnerTransactionTable.identify == identify,
                    PartnerTransactionTable.ingestion_key == ingestion_key,
                )
            )
            result = await session.execute(stmt)
            row = result.scalars().first()
            return row_to_data_container(row) if row else None

    async def find_by_source_file(self, source_file_id: UUID) -> list[DataContainer]:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable
        async with AsyncSession(self.engine) as session:
            stmt = select(PartnerTransactionTable).where(
                PartnerTransactionTable.source_file_id == source_file_id
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [row_to_data_container(r) for r in rows]

    async def find_by_date_range(self, identify: str, start: datetime, end: datetime) -> list[DataContainer]:
        if start.tzinfo is not None:
            start = start.replace(tzinfo=None)
        if end.tzinfo is not None:
            end = end.replace(tzinfo=None)

        from sqlalchemy import select, and_
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable
        async with AsyncSession(self.engine) as session:
            stmt = select(PartnerTransactionTable).where(
                and_(
                    PartnerTransactionTable.identify == identify,
                    PartnerTransactionTable.reconciliation_date >= start,
                    PartnerTransactionTable.reconciliation_date <= end
                )
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [row_to_data_container(r) for r in rows]

    async def find_reconciliation_keys_by_date_range(
        self,
        identify: str,
        start: datetime,
        end: datetime,
        *,
        exclude_source_file_id: UUID | None = None,
    ) -> set[str]:
        """Return the business keys used by reconciliation for a date range.

        Scope analysis only needs a compact key projection, not full partner
        transaction documents.  Keeping this query in the PostgreSQL adapter
        also ensures that the analysis uses the same key precedence as the
        reconciliation engine: trace, ``vspTransId``, then partner id.
        """
        if start.tzinfo is not None:
            start = start.replace(tzinfo=None)
        if end.tzinfo is not None:
            end = end.replace(tzinfo=None)

        from sqlalchemy import and_, select
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable

        conditions = [
            PartnerTransactionTable.identify == identify,
            PartnerTransactionTable.reconciliation_date >= start,
            PartnerTransactionTable.reconciliation_date <= end,
        ]
        if exclude_source_file_id is not None:
            conditions.append(PartnerTransactionTable.source_file_id != exclude_source_file_id)

        async with AsyncSession(self.engine) as session:
            stmt = select(
                PartnerTransactionTable.partner_id,
                PartnerTransactionTable.partner_trace,
                PartnerTransactionTable.partner_metadata,
            ).where(and_(*conditions))
            result = await session.execute(stmt)

        keys: set[str] = set()
        for partner_id, partner_trace, metadata in result.all():
            trace = str(partner_trace or "").strip()
            vsp_trans_id = ""
            if isinstance(metadata, dict):
                vsp_trans_id = str(metadata.get("vspTransId") or "").strip()
            key = trace or vsp_trans_id or str(partner_id or "").strip()
            if key:
                keys.add(key)
        return keys

    async def find_by_duplicate_key(self, identify: str, reconciliation_date: datetime, trace: str) -> Optional[DataContainer]:
        if reconciliation_date.tzinfo is not None:
            reconciliation_date = reconciliation_date.replace(tzinfo=None)

        from sqlalchemy import select, and_
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable
        async with AsyncSession(self.engine) as session:
            stmt = select(PartnerTransactionTable).where(
                and_(
                    PartnerTransactionTable.identify == identify,
                    PartnerTransactionTable.reconciliation_date == reconciliation_date,
                    PartnerTransactionTable.partner_trace == trace
                )
            )
            result = await session.execute(stmt)
            row = result.scalars().first()
            return row_to_data_container(row) if row else None

    async def find_many(self, query: dict) -> list[DataContainer]:
        from sqlalchemy import select, and_
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable
        conditions = []
        for key, val in query.items():
            if key == "identify":
                conditions.append(PartnerTransactionTable.identify == val)
            elif key in ("reconciliationDate", "reconciliation_date"):
                if isinstance(val, dict):
                    for op, limit_val in val.items():
                        if hasattr(limit_val, "tzinfo") and limit_val.tzinfo is not None:
                            limit_val = limit_val.replace(tzinfo=None)
                        if op == "$gte":
                            conditions.append(PartnerTransactionTable.reconciliation_date >= limit_val)
                        elif op == "$lte":
                            conditions.append(PartnerTransactionTable.reconciliation_date <= limit_val)
                else:
                    if hasattr(val, "tzinfo") and val.tzinfo is not None:
                        val = val.replace(tzinfo=None)
                    conditions.append(PartnerTransactionTable.reconciliation_date == val)
            elif key in ("partnerData.trace", "partner_trace"):
                conditions.append(PartnerTransactionTable.partner_trace == val)
            elif key in ("partnerData.status", "partner_status"):
                conditions.append(PartnerTransactionTable.partner_status == val)
            elif key in ("partnerData.amount", "partner_amount"):
                if isinstance(val, dict):
                    for op, limit_val in val.items():
                        from bson.decimal128 import Decimal128
                        from decimal import Decimal
                        if isinstance(limit_val, Decimal128):
                            limit_val = limit_val.to_decimal()
                        elif not isinstance(limit_val, Decimal):
                            limit_val = Decimal(str(limit_val))

                        if op == "$gte":
                            conditions.append(PartnerTransactionTable.partner_amount >= limit_val)
                        elif op == "$lte":
                            conditions.append(PartnerTransactionTable.partner_amount <= limit_val)
                else:
                    from bson.decimal128 import Decimal128
                    from decimal import Decimal
                    if isinstance(val, Decimal128):
                        val = val.to_decimal()
                    elif not isinstance(val, Decimal):
                        val = Decimal(str(val))
                    conditions.append(PartnerTransactionTable.partner_amount == val)
            elif key in ("sourceFileId", "source_file_id"):
                from uuid import UUID
                if isinstance(val, str):
                    val = UUID(val)
                conditions.append(PartnerTransactionTable.source_file_id == val)

        async with AsyncSession(self.engine) as session:
            stmt = select(PartnerTransactionTable)
            if conditions:
                stmt = stmt.where(and_(*conditions))
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [row_to_data_container(r) for r in rows]

    async def find_by_id(self, transaction_id: UUID | str) -> Optional[DataContainer]:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable

        if isinstance(transaction_id, str):
            try:
                transaction_id = UUID(transaction_id)
            except ValueError:
                return None
        async with AsyncSession(self.engine) as session:
            result = await session.execute(
                select(PartnerTransactionTable).where(
                    PartnerTransactionTable.id == transaction_id
                )
            )
            row = result.scalars().first()
            return row_to_data_container(row) if row else None

    async def count(self, query: Optional[dict] = None) -> int:
        return len(await self.find_many(query or {}))

    async def count_by_source_file(self, source_file_id: UUID | str) -> int:
        return await self.count({"sourceFileId": source_file_id})

    async def count_by_partner(self, query: Optional[dict] = None) -> dict[str, int]:
        records = await self.find_many(query or {})
        counts: dict[str, int] = {}
        for record in records:
            counts[record.identify] = counts.get(record.identify, 0) + 1
        return counts

    async def delete_by_source_file(self, source_file_id: UUID | str) -> int:
        from sqlalchemy import delete
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable

        if isinstance(source_file_id, str):
            source_file_id = UUID(source_file_id)
        async with self.engine.begin() as conn:
            result = await conn.execute(
                delete(PartnerTransactionTable).where(
                    PartnerTransactionTable.source_file_id == source_file_id
                )
            )
            return int(result.rowcount or 0)

    async def delete_by_partner(self, partner: str) -> int:
        """Delete canonical partner transactions for an isolated test/maintenance scope."""
        from sqlalchemy import delete
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable

        async with self.engine.begin() as conn:
            result = await conn.execute(
                delete(PartnerTransactionTable).where(
                    PartnerTransactionTable.identify == partner,
                )
            )
            return int(result.rowcount or 0)

    async def rebind_source_file_by_ingestion_keys(
        self, identify: str, ingestion_keys: list[str], source_file_id: UUID | str
    ) -> int:
        """Rebind existing canonical rows to the current logical file claim."""
        if not ingestion_keys:
            return 0
        from sqlalchemy import update
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable

        if isinstance(source_file_id, str):
            source_file_id = UUID(source_file_id)
        async with self.engine.begin() as conn:
            result = await conn.execute(
                update(PartnerTransactionTable)
                .where(
                    PartnerTransactionTable.identify == identify,
                    PartnerTransactionTable.ingestion_key.in_(ingestion_keys),
                )
                .values(source_file_id=source_file_id)
            )
            return int(result.rowcount or 0)
