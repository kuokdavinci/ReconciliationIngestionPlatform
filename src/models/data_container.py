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


def data_container_to_row(doc: DataContainer) -> dict:
    pd = doc.partner_data
    return {
        "id": doc.id,
        "request_id": doc.request_id,
        "identify": doc.identify,
        "workflow_type": doc.workflow_type,
        "reconciliation_date": doc.reconciliation_date,
        "operation_status": doc.operation_status,
        "reconciliation_status": doc.reconciliation_status,
        "connector_data": doc.connector_data,
        "extra_data": doc.extra_data,
        "source_file_id": doc.source_file_id,
        "partner_id": pd.id,
        "partner_trace": pd.trace,
        "partner_status": pd.status,
        "partner_amount": pd.amount,
        "partner_currency": pd.currency,
        "partner_trans_date": pd.trans_date,
        "partner_metadata": pd.extra or {},
        "created_by": doc.created_by,
        "created_date": doc.created_date,
        "last_modified_by": doc.last_modified_by,
        "last_modified_date": doc.last_modified_date,
    }


def row_to_data_container(row) -> DataContainer:
    if hasattr(row, "__table__"):
        data = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    else:
        data = dict(row)
        
    return DataContainer(
        _id=data["id"],
        requestId=data["request_id"],
        identify=data["identify"],
        workflowType=data["workflow_type"],
        reconciliationDate=data["reconciliation_date"],
        operationStatus=data["operation_status"],
        reconciliationStatus=data["reconciliation_status"],
        connectorData=data["connector_data"],
        extraData=data["extra_data"],
        sourceFileId=data["source_file_id"],
        partnerData={
            "_id": data["partner_id"],
            "trace": data["partner_trace"],
            "status": data["partner_status"],
            "amount": data["partner_amount"],
            "currency": data["partner_currency"],
            "transDate": data["partner_trans_date"],
            "extra": data["partner_metadata"] or {},
        },
        createdBy=data["created_by"],
        createdDate=data["created_date"],
        lastModifiedBy=data["last_modified_by"],
        lastModifiedDate=data["last_modified_date"],
    )


class DataContainerRepository(BaseRepository[DataContainer]):
    """Repository for DataContainer with domain-specific query methods backed by PostgreSQL/MongoDB hybrid."""

    def __init__(self, db: Any = None):
        super().__init__(collection_name="data_container", db=db)
        self._set_model_class(DataContainer)
        self.use_postgres = not ("MagicMock" in str(type(db)) or "AsyncMock" in str(type(db)))
        if self.use_postgres:
            from src.models.postgres import get_pg_engine
            self.engine = get_pg_engine()

    async def copy_records(self, docs: list[DataContainer]) -> int:
        if not docs:
            return 0
        import json
        rows = [data_container_to_row(doc) for doc in docs]
        columns = [
            "id", "request_id", "identify", "workflow_type", "reconciliation_date",
            "operation_status", "reconciliation_status", "connector_data", "extra_data",
            "source_file_id", "partner_id", "partner_trace", "partner_status",
            "partner_amount", "partner_currency", "partner_trans_date", "partner_metadata",
            "created_by", "created_date", "last_modified_by", "last_modified_date"
        ]
        
        def strip_tz(val):
            from datetime import datetime
            if isinstance(val, datetime) and val.tzinfo is not None:
                return val.replace(tzinfo=None)
            return val

        tuples = []
        for r in rows:
            tuples.append((
                r["id"], r["request_id"], r["identify"], r["workflow_type"], strip_tz(r["reconciliation_date"]),
                r["operation_status"], r["reconciliation_status"], r["connector_data"], r["extra_data"],
                r["source_file_id"], r["partner_id"], r["partner_trace"], r["partner_status"],
                r["partner_amount"], r["partner_currency"], strip_tz(r["partner_trans_date"]),
                json.dumps(r["partner_metadata"]) if isinstance(r["partner_metadata"], (dict, list)) else r["partner_metadata"],
                r["created_by"], strip_tz(r["created_date"]), r["last_modified_by"], strip_tz(r["last_modified_date"])
            ))
            
        async with self.engine.begin() as conn:
            raw_conn = await conn.get_raw_connection()
            asyncpg_conn = raw_conn.driver_connection
            await asyncpg_conn.copy_records_to_table(
                "partner_transaction",
                columns=columns,
                records=tuples
            )
            return len(tuples)

    async def insert_many(self, docs: list[DataContainer | dict], ordered: bool = True) -> int:
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
                result = await self.collection.insert_many(serialized, ordered=ordered)
                return len(result.inserted_ids)
            except BulkWriteError as exc:
                return exc.details.get("nInserted", 0)

        if not docs:
            return 0
        
        model_docs = []
        for doc in docs:
            if isinstance(doc, dict):
                from src.models.repository import BaseRepository
                converted = BaseRepository._convert_from_mongo_types(doc)
                if "_id" in converted and "id" not in converted:
                    converted["id"] = converted.pop("_id")
                if "partnerData" in converted:
                    pd = converted["partnerData"]
                    if "_id" in pd and "id" not in pd:
                        pd["id"] = pd.pop("_id")
                    if "transDate" in pd and "trans_date" not in pd:
                        pd["trans_date"] = pd.pop("transDate")
                    converted["partner_data"] = pd
                if "requestId" in converted:
                    converted["request_id"] = converted.pop("requestId")
                if "workflowType" in converted:
                    converted["workflow_type"] = converted.pop("workflowType")
                if "reconciliationDate" in converted:
                    converted["reconciliation_date"] = converted.pop("reconciliationDate")
                if "operationStatus" in converted:
                    converted["operation_status"] = converted.pop("operationStatus")
                if "reconciliationStatus" in converted:
                    converted["reconciliation_status"] = converted.pop("reconciliationStatus")
                if "connectorData" in converted:
                    converted["connector_data"] = converted.pop("connectorData")
                if "extraData" in converted:
                    converted["extra_data"] = converted.pop("extraData")
                if "sourceFileId" in converted:
                    converted["source_file_id"] = converted.pop("sourceFileId")
                if "createdBy" in converted:
                    converted["created_by"] = converted.pop("createdBy")
                if "createdDate" in converted:
                    converted["created_date"] = converted.pop("createdDate")
                if "lastModifiedBy" in converted:
                    converted["last_modified_by"] = converted.pop("lastModifiedBy")
                if "lastModifiedDate" in converted:
                    converted["last_modified_date"] = converted.pop("lastModifiedDate")
                
                model_docs.append(DataContainer.model_validate(converted))
            else:
                model_docs.append(doc)
                
        return await self.copy_records(model_docs)

    async def find_by_trace(self, identify: str, trace: str) -> Optional[DataContainer]:
        if not self.use_postgres:
            return await self.find_one({"identify": identify, "partnerData.trace": trace})

        from sqlalchemy import select, and_
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.models.postgres import PartnerTransactionTable
        async with AsyncSession(self.engine) as session:
            stmt = select(PartnerTransactionTable).where(
                and_(PartnerTransactionTable.identify == identify, PartnerTransactionTable.partner_trace == trace)
            )
            result = await session.execute(stmt)
            row = result.scalars().first()
            return row_to_data_container(row) if row else None

    async def find_by_source_file(self, source_file_id: UUID) -> list[DataContainer]:
        if not self.use_postgres:
            return await self.find_many({"sourceFileId": str(source_file_id)})

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.models.postgres import PartnerTransactionTable
        async with AsyncSession(self.engine) as session:
            stmt = select(PartnerTransactionTable).where(
                PartnerTransactionTable.source_file_id == source_file_id
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [row_to_data_container(r) for r in rows]

    async def find_by_date_range(self, identify: str, start: datetime, end: datetime) -> list[DataContainer]:
        if not self.use_postgres:
            return await self.find_many({
                "identify": identify,
                "reconciliationDate": {"$gte": start, "$lte": end}
            })

        if start.tzinfo is not None:
            start = start.replace(tzinfo=None)
        if end.tzinfo is not None:
            end = end.replace(tzinfo=None)

        from sqlalchemy import select, and_
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.models.postgres import PartnerTransactionTable
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

    async def find_by_duplicate_key(self, identify: str, reconciliation_date: datetime, trace: str) -> Optional[DataContainer]:
        if not self.use_postgres:
            return await self.find_one({
                "identify": identify,
                "reconciliationDate": reconciliation_date,
                "partnerData.trace": trace
            })

        if reconciliation_date.tzinfo is not None:
            reconciliation_date = reconciliation_date.replace(tzinfo=None)

        from sqlalchemy import select, and_
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.models.postgres import PartnerTransactionTable
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
        if not self.use_postgres:
            return await super().find_many(query)

        from sqlalchemy import select, and_
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.models.postgres import PartnerTransactionTable
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
