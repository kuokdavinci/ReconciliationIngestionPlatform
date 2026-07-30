"""ReconciliationResult model and repository for storing matching output."""

from datetime import datetime
from decimal import Decimal
from typing import Optional, Any
from pydantic import BaseModel, ConfigDict, Field
from src.core.enums import ReconciliationStatus


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
    partner: str = Field(alias="partner")
    date: str = Field(alias="date")
    partner_txn_id: str = Field(alias="partnerTxnId")
    internal_txn_id: Optional[str] = Field(default=None, alias="internalTxnId")

    partner_amount: Optional[Decimal] = Field(default=None, alias="partnerAmount")
    internal_amount: Optional[Decimal] = Field(default=None, alias="internalAmount")

    partner_status: Optional[str] = Field(default=None, alias="partnerStatus")
    internal_status: Optional[str] = Field(default=None, alias="internalStatus")

    reconciliation_status: ReconciliationStatus = Field(alias="reconciliationStatus")
    reconciliation_run_id: Optional[str] = Field(default=None, alias="reconciliationRunId")
    source_file_id: Optional[str] = Field(default=None, alias="sourceFileId")
    scope_type: Optional[str] = Field(default=None, alias="scopeType")
    mapping_version: Optional[str] = Field(default=None, alias="mappingVersion")

    partner_record_id: Optional[str] = Field(default=None, alias="partnerRecordId")
    internal_record_id: Optional[str] = Field(default=None, alias="internalRecordId")

    created_at: datetime = Field(
        default_factory=datetime.utcnow, alias="createdAt"
    )


def reconciliation_result_to_row(doc: ReconciliationResult) -> dict:
    return {
        "id": doc.id,
        "partner": doc.partner,
        "date": doc.date,
        "partner_txn_id": doc.partner_txn_id,
        "internal_txn_id": doc.internal_txn_id,
        "partner_amount": doc.partner_amount,
        "internal_amount": doc.internal_amount,
        "partner_status": doc.partner_status,
        "internal_status": doc.internal_status,
        "reconciliation_status": doc.reconciliation_status.value if hasattr(doc.reconciliation_status, "value") else str(doc.reconciliation_status),
        "reconciliation_run_id": doc.reconciliation_run_id,
        "source_file_id": doc.source_file_id,
        "scope_type": doc.scope_type,
        "mapping_version": doc.mapping_version,
        "partner_record_id": doc.partner_record_id,
        "internal_record_id": doc.internal_record_id,
        "created_at": doc.created_at,
    }


def row_to_reconciliation_result(row) -> ReconciliationResult:
    if hasattr(row, "__table__"):
        data = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    else:
        data = dict(row)
    return ReconciliationResult(
        _id=data["id"],
        partner=data["partner"],
        date=data["date"],
        partnerTxnId=data["partner_txn_id"],
        internalTxnId=data["internal_txn_id"],
        partnerAmount=data["partner_amount"],
        internalAmount=data["internal_amount"],
        partnerStatus=data["partner_status"],
        internalStatus=data["internal_status"],
        reconciliationStatus=data["reconciliation_status"],
        reconciliationRunId=data["reconciliation_run_id"],
        sourceFileId=data["source_file_id"],
        scopeType=data["scope_type"],
        mappingVersion=data["mapping_version"],
        partnerRecordId=data["partner_record_id"],
        internalRecordId=data["internal_record_id"],
        createdAt=data["created_at"],
    )




class ReconciliationResultRepository:
    """PostgreSQL repository for reconciliation result data."""

    def __init__(self, db: Any = None, engine: Any = None):
        del db
        if engine is None:
            from src.models.postgres import get_pg_engine

            engine = get_pg_engine()
        self.engine = engine

    async def insert_many(self, docs: list[ReconciliationResult | dict], ordered: bool = True) -> int:
        """Bulk insert multiple ReconciliationResult documents."""
        if not docs:
            return 0
        
        rows = []
        for doc in docs:
            if isinstance(doc, dict):
                from src.models.repository import BaseRepository
                converted = BaseRepository._convert_from_mongo_types(doc)
                if "_id" in converted and "id" not in converted:
                    converted["id"] = converted.pop("_id")
                if "partnerTxnId" in converted:
                    converted["partner_txn_id"] = converted.pop("partnerTxnId")
                if "internalTxnId" in converted:
                    converted["internal_txn_id"] = converted.pop("internalTxnId")
                if "partnerAmount" in converted:
                    converted["partner_amount"] = converted.pop("partnerAmount")
                if "internalAmount" in converted:
                    converted["internal_amount"] = converted.pop("internalAmount")
                if "partnerStatus" in converted:
                    converted["partner_status"] = converted.pop("partnerStatus")
                if "internalStatus" in converted:
                    converted["internal_status"] = converted.pop("internalStatus")
                if "reconciliationStatus" in converted:
                    converted["reconciliation_status"] = converted.pop("reconciliationStatus")
                if "reconciliationRunId" in converted:
                    converted["reconciliation_run_id"] = converted.pop("reconciliationRunId")
                if "sourceFileId" in converted:
                    converted["source_file_id"] = converted.pop("sourceFileId")
                if "scopeType" in converted:
                    converted["scope_type"] = converted.pop("scopeType")
                if "mappingVersion" in converted:
                    converted["mapping_version"] = converted.pop("mappingVersion")
                if "partnerRecordId" in converted:
                    converted["partner_record_id"] = converted.pop("partnerRecordId")
                if "internalRecordId" in converted:
                    converted["internal_record_id"] = converted.pop("internalRecordId")
                if "createdAt" in converted:
                    converted["created_at"] = converted.pop("createdAt")
                    
                model_doc = ReconciliationResult.model_validate(converted)
            else:
                model_doc = doc
            rows.append(reconciliation_result_to_row(model_doc))

        from sqlalchemy import insert
        from src.models.postgres import ReconciliationResultTable
        async with self.engine.begin() as conn:
            stmt = insert(ReconciliationResultTable)
            await conn.execute(stmt, rows)
            return len(rows)

    async def find_by_id(self, result_id: Any) -> Optional[ReconciliationResult]:
        from uuid import UUID
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.models.postgres import ReconciliationResultTable

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
        from src.models.postgres import ReconciliationResultTable
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
        from src.models.postgres import ReconciliationResultTable
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
        from src.models.postgres import ReconciliationResultTable
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
        from src.models.postgres import ReconciliationResultTable

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
        from src.models.postgres import ReconciliationResultTable

        async with AsyncSession(self.engine) as session:
            result = await session.execute(
                select(ReconciliationResultTable.partner)
                .where(ReconciliationResultTable.date == date)
                .distinct()
                .order_by(ReconciliationResultTable.partner.asc())
            )
            return list(result.scalars().all())

    async def delete_by_partner_and_date(self, partner: str, date: str) -> int:
        from sqlalchemy import and_, delete
        from src.models.postgres import ReconciliationResultTable

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
        from src.models.postgres import ReconciliationResultTable
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
        from src.models.postgres import ReconciliationResultTable
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
        from src.models.postgres import ReconciliationResultTable
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
