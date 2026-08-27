"""MongoDB adapter for manual reconciliation run state."""

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.domain.reconciliation.models import ReconciliationRun
from src.infrastructure.persistence.mongo_repository import BaseRepository


class ReconciliationRunRepository(BaseRepository[ReconciliationRun]):
    """Repository for manually triggered reconciliation runs."""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="reconciliation_run", db=db)
        self._set_model_class(ReconciliationRun)

    async def find_latest_by_partner_and_date(
        self, partner: str, date: str
    ) -> Optional[ReconciliationRun]:
        raw = await self.collection.find_one(
            {"partner": partner, "date": date},
            sort=[("createdAt", -1)],
        )
        if raw is None:
            return None
        return self._from_mongo(raw)
