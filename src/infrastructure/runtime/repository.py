"""MongoDB adapter for runtime workflow visibility."""

from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.domain.runtime.models import PartnerRuntimeRun
from src.infrastructure.persistence.mongo_repository import BaseRepository


class PartnerRuntimeRunRepository(BaseRepository[PartnerRuntimeRun]):
    """Repository for fetch/ingest/reconcile runtime states."""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="partner_runtime_run", db=db)
        self._set_model_class(PartnerRuntimeRun)

    async def update_fields(
        self,
        run_id: str,
        fields: dict[str, Any],
        *,
        attempt_event: dict[str, Any] | None = None,
    ) -> None:
        operation: dict[str, Any] = {"$set": fields}
        if attempt_event is not None:
            operation["$push"] = {"attemptHistory": attempt_event}
        await self.collection.update_one({"_id": run_id}, operation)

    async def find_latest_by_partner_and_date(
        self, partner: str, date: str
    ) -> Optional[PartnerRuntimeRun]:
        raw = await self.collection.find_one(
            {"partner": partner, "date": date},
            sort=[("createdAt", -1)],
        )
        if raw is None:
            return None
        return self._from_mongo(raw)

    async def find_latest_by_partner(self, partner: str) -> Optional[PartnerRuntimeRun]:
        raw = await self.collection.find_one(
            {"partner": partner},
            sort=[("createdAt", -1)],
        )
        if raw is None:
            return None
        return self._from_mongo(raw)

    async def find_recent_by_partner(
        self, partner: str, limit: int = 5
    ) -> list[PartnerRuntimeRun]:
        """Return recent attempts for operator correlation/debugging."""
        cursor = self.collection.find({"partner": partner})
        if hasattr(cursor, "sort"):
            cursor = cursor.sort("createdAt", -1)
        if hasattr(cursor, "limit"):
            cursor = cursor.limit(limit)
        result: list[PartnerRuntimeRun] = []
        async for raw in cursor:
            result.append(self._from_mongo(raw))
            if len(result) >= limit:
                break
        return result
