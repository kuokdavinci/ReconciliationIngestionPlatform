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

    async def find_by_partner_and_date(
        self, partner: str, date: str
    ) -> list[ReconciliationResult]:
        """Find all results for a partner on a specific date."""
        return await self.find_many({"partner": partner, "date": date})

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
        query: dict[str, object] = {"partner": partner, "date": date}
        if status is not None:
            query["reconciliationStatus"] = status.value
        if reconciliation_run_id is not None:
            query["reconciliationRunId"] = reconciliation_run_id
        elif source_file_id is not None:
            query["sourceFileId"] = source_file_id

        total = await self.collection.count_documents(query)
        cursor = self.collection.find(query).sort("_id", 1).skip(offset).limit(limit)
        records: list[ReconciliationResult] = []
        async for raw in cursor:
            records.append(self._from_mongo(raw))
        return records, total

    async def find_by_partner_date_and_status(
        self, partner: str, date: str, status: ReconciliationStatus
    ) -> list[ReconciliationResult]:
        """Find results for a partner+date filtered by reconciliation status."""
        return await self.find_many({
            "partner": partner,
            "date": date,
            "reconciliationStatus": status.value,
        })

    async def count_by_status(
        self, partner: str, date: str
        , *, reconciliation_run_id: str | None = None, source_file_id: str | None = None
    ) -> dict[str, int]:
        """Aggregate reconciliation results by status.

        Returns dict like {"MATCHED": 1450, "AMOUNT_MISMATCH": 30, ...}
        """
        match_query: dict[str, object] = {"partner": partner, "date": date}
        if reconciliation_run_id is not None:
            match_query["reconciliationRunId"] = reconciliation_run_id
        elif source_file_id is not None:
            match_query["sourceFileId"] = source_file_id
        pipeline = [
            {"$match": match_query},
            {"$group": {"_id": "$reconciliationStatus", "count": {"$sum": 1}}},
        ]
        cursor = self.collection.aggregate(pipeline)
        result: dict[str, int] = {}
        async for doc in cursor:
            result[str(doc["_id"])] = doc["count"]
        return result

    async def get_total_amounts(
        self, partner: str, date: str
        , *, reconciliation_run_id: str | None = None, source_file_id: str | None = None
    ) -> dict[str, object]:
        """Get sum of partner_amount and internal_amount for a partner+date."""
        match_query: dict[str, object] = {"partner": partner, "date": date}
        if reconciliation_run_id is not None:
            match_query["reconciliationRunId"] = reconciliation_run_id
        elif source_file_id is not None:
            match_query["sourceFileId"] = source_file_id
        pipeline = [
            {"$match": match_query},
            {
                "$group": {
                    "_id": None,
                    "total_partner_amount": {"$sum": "$partnerAmount"},
                    "total_internal_amount": {"$sum": "$internalAmount"},
                }
            },
        ]
        cursor = self.collection.aggregate(pipeline)
        from bson.decimal128 import Decimal128
        from decimal import Decimal
        async for doc in cursor:
            pa = doc.get("total_partner_amount")
            ia = doc.get("total_internal_amount")
            return {
                "total_partner_amount": pa.to_decimal() if isinstance(pa, Decimal128) else (Decimal(str(pa)) if pa is not None else None),
                "total_internal_amount": ia.to_decimal() if isinstance(ia, Decimal128) else (Decimal(str(ia)) if ia is not None else None),
            }
        return {"total_partner_amount": None, "total_internal_amount": None}
