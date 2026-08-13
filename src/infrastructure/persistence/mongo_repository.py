"""Shared MongoDB repository implementation."""

from typing import Any, Generic, Optional, TypeVar
from uuid import UUID

from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class BaseRepository(Generic[T]):
    """Generic async CRUD adapter for MongoDB collections."""

    def __init__(self, collection_name: str, db: AsyncIOMotorDatabase):
        self.collection_name = collection_name
        self.collection = db[collection_name]
        self._model_class: type[T] | None = None

    def _set_model_class(self, model_class: type[T]) -> None:
        self._model_class = model_class

    def _to_mongo(self, doc: T) -> dict:
        data = doc.model_dump(by_alias=True, exclude_none=False)
        return self._convert_special_types(data)

    @staticmethod
    def _convert_special_types(obj: Any) -> Any:
        from decimal import Decimal
        from bson.decimal128 import Decimal128

        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, Decimal):
            return Decimal128(obj)
        if isinstance(obj, dict):
            return {k: BaseRepository._convert_special_types(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [BaseRepository._convert_special_types(item) for item in obj]
        return obj

    @staticmethod
    def _convert_uuids(obj: Any) -> Any:
        return BaseRepository._convert_special_types(obj)

    async def create(self, doc: T) -> T:
        data = self._to_mongo(doc)
        await self.collection.insert_one(data)
        return doc

    async def find_one(self, query: dict, *, sort: list[tuple[str, int]] | None = None) -> Optional[T]:
        raw = await self.collection.find_one(query, sort=sort) if sort else await self.collection.find_one(query)
        if raw is None:
            return None
        return self._from_mongo(raw)

    async def find_many(self, query: dict) -> list[T]:
        cursor = self.collection.find(query)
        results = []
        async for raw in cursor:
            results.append(self._from_mongo(raw))
        return results

    async def update_one(self, query: dict, update: dict) -> bool:
        result = await self.collection.update_one(query, {"$set": update})
        return result.modified_count > 0

    async def delete_one(self, query: dict) -> bool:
        result = await self.collection.delete_one(query)
        return result.deleted_count > 0

    @staticmethod
    def _convert_from_mongo_types(obj: Any) -> Any:
        from src.infrastructure.persistence.mongo_values import convert_from_mongo_types

        return convert_from_mongo_types(obj)

    def _from_mongo(self, raw: dict) -> T:
        if self._model_class is None:
            raise RuntimeError(
                f"Model class not set for {self.__class__.__name__}. "
                "Call _set_model_class() in the subclass constructor."
            )
        if "_id" in raw and hasattr(raw["_id"], "__str__"):
            raw["_id"] = str(raw["_id"])
        raw = self._convert_from_mongo_types(raw)
        return self._model_class.model_validate(raw)
