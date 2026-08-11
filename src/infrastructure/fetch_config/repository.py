"""MongoDB repository for partner fetch configuration."""

from datetime import UTC, datetime
from typing import Optional

from src.domain.fetch_config.models import FetchConfig


class FetchConfigRepository:
    """Repository for fetch configuration CRUD operations."""

    def __init__(self, db):
        self._collection = db["fetch_config"]

    async def create(self, config: FetchConfig) -> FetchConfig:
        doc = config.model_dump(by_alias=True, exclude_none=False)
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])
        await self._collection.insert_one(doc)
        return config

    async def find_by_partner(self, partner: str) -> Optional[FetchConfig]:
        raw = await self._collection.find_one({"partner": partner})
        if raw is None:
            return None
        return self._from_mongo(raw)

    async def find_by_id(self, config_id: str) -> Optional[FetchConfig]:
        raw = await self._collection.find_one({"_id": config_id})
        if raw is None:
            return None
        return self._from_mongo(raw)

    async def find_enabled(self) -> list[FetchConfig]:
        cursor = self._collection.find({"enabled": True})
        results = []
        async for raw in cursor:
            results.append(self._from_mongo(raw))
        return results

    async def update(self, config: FetchConfig) -> bool:
        config.updated_at = datetime.now(UTC)
        doc = config.model_dump(by_alias=True, exclude_none=False)
        result = await self._collection.update_one({"_id": config.id}, {"$set": doc})
        return result.modified_count > 0

    async def delete_by_partner(self, partner: str) -> bool:
        result = await self._collection.delete_one({"partner": partner})
        return result.deleted_count > 0

    @staticmethod
    def _from_mongo(raw: dict) -> FetchConfig:
        if "_id" in raw and hasattr(raw["_id"], "__str__"):
            raw["_id"] = str(raw["_id"])
        return FetchConfig.model_validate(raw)
