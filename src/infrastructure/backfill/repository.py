"""MongoDB adapter for durable backfill runs."""

from datetime import UTC, date, datetime
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.domain.backfill.models import BackfillRun, BackfillRunStatus
from src.infrastructure.persistence.mongo_repository import BaseRepository


class BackfillRunRepository(BaseRepository[BackfillRun]):
    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="backfill_run", db=db)
        self._set_model_class(BackfillRun)

    async def find_by_id(self, backfill_run_id: str) -> Optional[BackfillRun]:
        return await self.find_one({"_id": backfill_run_id})

    async def find_latest_active_by_partner(self, partner: str) -> Optional[BackfillRun]:
        """Return the latest durable backfill checkpoint for operator resumption."""
        return await self.find_one(
            {
                "partner": partner,
                "mode": "BACKFILL",
                "status": {
                    "$in": [
                        BackfillRunStatus.WAITING_CONFIG.value,
                        BackfillRunStatus.QUEUED.value,
                        BackfillRunStatus.RUNNING.value,
                        BackfillRunStatus.FAILED.value,
                    ]
                },
            },
            sort=[("updatedAt", -1), ("createdAt", -1)],
        )

    async def create(self, doc: BackfillRun) -> BackfillRun:
        payload = self._to_mongo(doc)
        for key in ("fromDate", "toDate", "currentDate"):
            if isinstance(payload.get(key), date) and not isinstance(payload[key], datetime):
                payload[key] = payload[key].isoformat()
        for day in payload.get("days", []):
            if isinstance(day.get("businessDate"), date) and not isinstance(day["businessDate"], datetime):
                day["businessDate"] = day["businessDate"].isoformat()
        await self.collection.insert_one(payload)
        return doc

    async def update_status(self, backfill_run_id: str, **changes: Any) -> bool:
        changes = {
            key: value.isoformat()
            if isinstance(value, date) and not isinstance(value, datetime)
            else value
            for key, value in changes.items()
        }
        payload = {"updatedAt": datetime.now(UTC), **changes}
        result = await self.collection.update_one(
            {"_id": backfill_run_id},
            {"$set": self._convert_special_types(payload)},
        )
        return result.modified_count > 0

    async def claim_day(self, backfill_run_id: str, business_date: str) -> bool:
        result = await self.collection.update_one(
            {
                "_id": backfill_run_id,
                "days.businessDate": business_date,
                "days.status": {"$in": ["PENDING", "WAITING_CONFIG"]},
            },
            {
                "$set": {
                    "currentDate": business_date,
                    "updatedAt": datetime.now(UTC),
                    "days.$.status": "RUNNING",
                    "days.$.updatedAt": datetime.now(UTC),
                }
            },
        )
        return result.modified_count > 0

    async def update_day(self, backfill_run_id: str, business_date: str, **changes: Any) -> bool:
        payload = {
            "days.$.updatedAt": datetime.now(UTC),
            **{f"days.$.{key}": value for key, value in changes.items()},
            "updatedAt": datetime.now(UTC),
        }
        result = await self.collection.update_one(
            {"_id": backfill_run_id, "days.businessDate": business_date},
            {"$set": self._convert_special_types(payload)},
        )
        return result.modified_count > 0
