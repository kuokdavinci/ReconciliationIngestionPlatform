"""PostgreSQL adapter for reconciliation result data."""

from collections.abc import Sequence
from typing import Optional, Any

from src.core.enums import ReconciliationStatus
from src.domain.reconciliation.models import ReconciliationResult
from src.infrastructure.postgres.reconciliation_result_mappers import (
    document_to_reconciliation_result,
    reconciliation_result_to_row,
    row_to_reconciliation_result,
)



class ReconciliationResultRepository:
    """PostgreSQL repository for reconciliation result data."""

    def __init__(self, db: Any = None, engine: Any = None):
        del db
        if engine is None:
            from src.infrastructure.persistence.postgres_connection import get_pg_engine

            engine = get_pg_engine()
        self.engine = engine

    async def insert_many(
        self, docs: Sequence[ReconciliationResult | dict], ordered: bool = True
    ) -> int:
        """Bulk insert multiple ReconciliationResult documents."""
        if not docs:
            return 0

        rows = []
        for doc in docs:
            if isinstance(doc, dict):
                model_doc = document_to_reconciliation_result(doc)
            else:
                model_doc = doc
            rows.append(reconciliation_result_to_row(model_doc))

        from sqlalchemy import insert
        from src.infrastructure.persistence.postgres_schema import ReconciliationResultTable
        async with self.engine.begin() as conn:
            stmt = insert(ReconciliationResultTable)
            await conn.execute(stmt, rows)
            return len(rows)

    async def find_by_id(self, result_id: Any) -> Optional[ReconciliationResult]:
        from uuid import UUID
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import ReconciliationResultTable

        try:
            uid = UUID(str(result_id))
        except (ValueError, TypeError):
            return None

        async with AsyncSession(self.engine) as session:
            stmt = select(ReconciliationResultTable).where(
                ReconciliationResultTable.id == uid
            )
            result = await session.execute(stmt)
            row = result.scalars().first()
            return row_to_reconciliation_result(row) if row else None

    async def find_by_partner_and_date(
        self, partner: str, date: str
        , *, reconciliation_run_id: str | None = None, source_file_id: str | None = None
    ) -> list[ReconciliationResult]:
        """Find all results for a partner on a specific date."""
        from sqlalchemy import select, and_
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import ReconciliationResultTable
        conditions = [ReconciliationResultTable.partner == partner, ReconciliationResultTable.date == date]
        if reconciliation_run_id is not None:
            if isinstance(reconciliation_run_id, dict) and "$in" in reconciliation_run_id:
                conditions.append(ReconciliationResultTable.reconciliation_run_id.in_(reconciliation_run_id["$in"]))
            elif isinstance(reconciliation_run_id, (list, tuple)):
                conditions.append(ReconciliationResultTable.reconciliation_run_id.in_(reconciliation_run_id))
            else:
                conditions.append(ReconciliationResultTable.reconciliation_run_id == reconciliation_run_id)
        elif source_file_id is not None:
            if isinstance(source_file_id, dict) and "$in" in source_file_id:
                conditions.append(ReconciliationResultTable.source_file_id.in_(source_file_id["$in"]))
            elif isinstance(source_file_id, (list, tuple)):
                conditions.append(ReconciliationResultTable.source_file_id.in_(source_file_id))
            else:
                conditions.append(ReconciliationResultTable.source_file_id == source_file_id)
        async with AsyncSession(self.engine) as session:
            stmt = select(ReconciliationResultTable).where(
                and_(*conditions)
            ).order_by(ReconciliationResultTable.id.asc())
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [row_to_reconciliation_result(r) for r in rows]

    async def find_page_by_partner_and_date(
        self,
        partner: str,
        date: str,
        *,
        status: ReconciliationStatus | None = None,
        reconciliation_run_id: str | None = None,
        source_file_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ReconciliationResult], int]:
        from sqlalchemy import select, and_, func
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import ReconciliationResultTable
        conditions = [ReconciliationResultTable.partner == partner, ReconciliationResultTable.date == date]
        if status is not None:
            conditions.append(ReconciliationResultTable.reconciliation_status == status.value)
        if reconciliation_run_id is not None:
            if isinstance(reconciliation_run_id, dict) and "$in" in reconciliation_run_id:
                conditions.append(ReconciliationResultTable.reconciliation_run_id.in_(reconciliation_run_id["$in"]))
            elif isinstance(reconciliation_run_id, (list, tuple)):
                conditions.append(ReconciliationResultTable.reconciliation_run_id.in_(reconciliation_run_id))
            else:
                conditions.append(ReconciliationResultTable.reconciliation_run_id == reconciliation_run_id)
        elif source_file_id is not None:
            if isinstance(source_file_id, dict) and "$in" in source_file_id:
                conditions.append(ReconciliationResultTable.source_file_id.in_(source_file_id["$in"]))
            elif isinstance(source_file_id, (list, tuple)):
                conditions.append(ReconciliationResultTable.source_file_id.in_(source_file_id))
            else:
                conditions.append(ReconciliationResultTable.source_file_id == source_file_id)

        async with AsyncSession(self.engine) as session:
            count_stmt = select(func.count()).select_from(ReconciliationResultTable).where(and_(*conditions))
            total_result = await session.execute(count_stmt)
            total = total_result.scalar() or 0

            stmt = select(ReconciliationResultTable).where(and_(*conditions)).order_by(ReconciliationResultTable.id.asc()).offset(offset).limit(limit)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            records = [row_to_reconciliation_result(r) for r in rows]
            return records, total

    async def find_by_partner_date_and_status(
        self, partner: str, date: str, status: ReconciliationStatus
    ) -> list[ReconciliationResult]:
        """Find results for a partner+date filtered by reconciliation status."""
        from sqlalchemy import select, and_
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import ReconciliationResultTable
        async with AsyncSession(self.engine) as session:
            stmt = select(ReconciliationResultTable).where(
                and_(
                    ReconciliationResultTable.partner == partner,
                    ReconciliationResultTable.date == date,
                    ReconciliationResultTable.reconciliation_status == status.value
                )
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [row_to_reconciliation_result(r) for r in rows]

    async def count_by_partner_and_date(self, partner: str, date: str) -> int:
        from sqlalchemy import and_, func, select
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import ReconciliationResultTable

        async with AsyncSession(self.engine) as session:
            result = await session.execute(
                select(func.count())
                .select_from(ReconciliationResultTable)
                .where(
                    and_(
                        ReconciliationResultTable.partner == partner,
                        ReconciliationResultTable.date == date,
                    )
                )
            )
            return int(result.scalar() or 0)

    async def distinct_partners_by_date(self, date: str) -> list[str]:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import ReconciliationResultTable

        async with AsyncSession(self.engine) as session:
            result = await session.execute(
                select(ReconciliationResultTable.partner)
                .where(ReconciliationResultTable.date == date)
                .distinct()
                .order_by(ReconciliationResultTable.partner.asc())
            )
            return list(result.scalars().all())

    async def delete_by_partner_and_date(
        self, partner: str, date: str, **kwargs: Any
    ) -> int:
        del kwargs
        from sqlalchemy import and_, delete
        from src.infrastructure.persistence.postgres_schema import ReconciliationResultTable

        async with self.engine.begin() as conn:
            result = await conn.execute(
                delete(ReconciliationResultTable).where(
                    and_(
                        ReconciliationResultTable.partner == partner,
                        ReconciliationResultTable.date == date,
                    )
                )
            )
            return int(result.rowcount or 0)

    async def count_by_status(
        self, partner: str, date: str
        , *, reconciliation_run_id: str | None = None, source_file_id: str | None = None
    ) -> dict[str, int]:
        from sqlalchemy import select, and_, func
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import ReconciliationResultTable
        conditions = [ReconciliationResultTable.partner == partner, ReconciliationResultTable.date == date]
        if reconciliation_run_id is not None:
            if isinstance(reconciliation_run_id, dict) and "$in" in reconciliation_run_id:
                conditions.append(ReconciliationResultTable.reconciliation_run_id.in_(reconciliation_run_id["$in"]))
            elif isinstance(reconciliation_run_id, (list, tuple)):
                conditions.append(ReconciliationResultTable.reconciliation_run_id.in_(reconciliation_run_id))
            else:
                conditions.append(ReconciliationResultTable.reconciliation_run_id == reconciliation_run_id)
        elif source_file_id is not None:
            if isinstance(source_file_id, dict) and "$in" in source_file_id:
                conditions.append(ReconciliationResultTable.source_file_id.in_(source_file_id["$in"]))
            elif isinstance(source_file_id, (list, tuple)):
                conditions.append(ReconciliationResultTable.source_file_id.in_(source_file_id))
            else:
                conditions.append(ReconciliationResultTable.source_file_id == source_file_id)

        async with AsyncSession(self.engine) as session:
            stmt = select(ReconciliationResultTable.reconciliation_status, func.count()).where(and_(*conditions)).group_by(ReconciliationResultTable.reconciliation_status)
            result = await session.execute(stmt)
            counts = {}
            for status, count in result.all():
                counts[status] = count
            return counts

    async def get_total_amounts(
        self, partner: str, date: str
        , *, reconciliation_run_id: str | None = None, source_file_id: str | None = None
    ) -> dict[str, object]:
        from sqlalchemy import select, and_, func
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import ReconciliationResultTable
        conditions = [ReconciliationResultTable.partner == partner, ReconciliationResultTable.date == date]
        if reconciliation_run_id is not None:
            if isinstance(reconciliation_run_id, dict) and "$in" in reconciliation_run_id:
                conditions.append(ReconciliationResultTable.reconciliation_run_id.in_(reconciliation_run_id["$in"]))
            elif isinstance(reconciliation_run_id, (list, tuple)):
                conditions.append(ReconciliationResultTable.reconciliation_run_id.in_(reconciliation_run_id))
            else:
                conditions.append(ReconciliationResultTable.reconciliation_run_id == reconciliation_run_id)
        elif source_file_id is not None:
            if isinstance(source_file_id, dict) and "$in" in source_file_id:
                conditions.append(ReconciliationResultTable.source_file_id.in_(source_file_id["$in"]))
            elif isinstance(source_file_id, (list, tuple)):
                conditions.append(ReconciliationResultTable.source_file_id.in_(source_file_id))
            else:
                conditions.append(ReconciliationResultTable.source_file_id == source_file_id)

        async with AsyncSession(self.engine) as session:
            stmt = select(func.sum(ReconciliationResultTable.partner_amount), func.sum(ReconciliationResultTable.internal_amount)).where(and_(*conditions))
            result = await session.execute(stmt)
            row = result.first()
            if row:
                return {
                    "total_partner_amount": row[0],
                    "total_internal_amount": row[1],
                }
            return {"total_partner_amount": None, "total_internal_amount": None}

    async def get_summary_metrics(
        self, partner: str, date: str
        , *, reconciliation_run_id: str | None = None, source_file_id: str | None = None
    ) -> dict[str, object]:
        by_status = await self.count_by_status(
            partner,
            date,
            reconciliation_run_id=reconciliation_run_id,
            source_file_id=source_file_id,
        )

        from sqlalchemy import select, and_, func, case
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import ReconciliationResultTable
        conditions = [ReconciliationResultTable.partner == partner, ReconciliationResultTable.date == date]
        if reconciliation_run_id is not None:
            if isinstance(reconciliation_run_id, dict) and "$in" in reconciliation_run_id:
                conditions.append(ReconciliationResultTable.reconciliation_run_id.in_(reconciliation_run_id["$in"]))
            elif isinstance(reconciliation_run_id, (list, tuple)):
                conditions.append(ReconciliationResultTable.reconciliation_run_id.in_(reconciliation_run_id))
            else:
                conditions.append(ReconciliationResultTable.reconciliation_run_id == reconciliation_run_id)
        elif source_file_id is not None:
            if isinstance(source_file_id, dict) and "$in" in source_file_id:
                conditions.append(ReconciliationResultTable.source_file_id.in_(source_file_id["$in"]))
            elif isinstance(source_file_id, (list, tuple)):
                conditions.append(ReconciliationResultTable.source_file_id.in_(source_file_id))
            else:
                conditions.append(ReconciliationResultTable.source_file_id == source_file_id)

        async with AsyncSession(self.engine) as session:
            stmt = select(
                func.sum(
                    case(
                        (
                            ReconciliationResultTable.reconciliation_status.in_([
                                ReconciliationStatus.AMOUNT_MISMATCH.value,
                                ReconciliationStatus.MULTIPLE_MISMATCH.value,
                                ReconciliationStatus.STATUS_MISMATCH.value,
                            ]),
                            func.abs(ReconciliationResultTable.partner_amount - ReconciliationResultTable.internal_amount),
                        ),
                        else_=0,
                    )
                )
            ).where(and_(*conditions))
            result = await session.execute(stmt)
            total_amount_mismatch = float(result.scalar() or 0.0)
            return {"by_status": by_status, "total_amount_mismatch": total_amount_mismatch}
