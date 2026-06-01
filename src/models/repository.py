"""Base repository class with common CRUD operations for MongoDB collections."""

from typing import Any, Generic, Optional, TypeVar
from uuid import UUID

from bson import UuidRepresentation
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class BaseRepository(Generic[T]):
    """Generic async repository providing common MongoDB CRUD operations.

    Each model-specific repository extends this class and adds
    domain-specific query methods.
    """

    def __init__(self, collection_name: str, db: AsyncIOMotorDatabase):
        self.collection_name = collection_name
        self.collection = db[collection_name]
        self._model_class: type[T] | None = None

    def _set_model_class(self, model_class: type[T]) -> None:
        """Set the pydantic model class for document conversion."""
        self._model_class = model_class

    def _to_mongo(self, doc: T) -> dict:
        """Convert a pydantic model to a MongoDB-compatible dict.

        UUIDs are converted to strings and Decimals are converted to Decimal128.
        """
        data = doc.model_dump(by_alias=True, exclude_none=False)
        return self._convert_special_types(data)

    @staticmethod
    def _convert_special_types(obj: Any) -> Any:
        """Recursively convert UUIDs to strings and Decimals to Decimal128."""
        from uuid import UUID
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
        """Legacy helper. Recursively convert UUID instances to strings."""
        return BaseRepository._convert_special_types(obj)

    async def create(self, doc: T) -> T:
        """Insert a document into the collection and return it with _id populated."""
        data = self._to_mongo(doc)
        result = await self.collection.insert_one(data)
        return doc

    async def find_one(self, query: dict) -> Optional[T]:
        """Find a single document matching the query."""
        raw = await self.collection.find_one(query)
        if raw is None:
            return None
        return self._from_mongo(raw)

    async def find_many(self, query: dict) -> list[T]:
        """Find all documents matching the query."""
        cursor = self.collection.find(query)
        results = []
        async for raw in cursor:
            results.append(self._from_mongo(raw))
        return results

    async def update_one(self, query: dict, update: dict) -> bool:
        """Update a single document matching the query.

        Returns True if a document was modified, False otherwise.
        """
        result = await self.collection.update_one(query, {"$set": update})
        return result.modified_count > 0

    async def delete_one(self, query: dict) -> bool:
        """Delete a single document matching the query.

        Returns True if a document was deleted, False otherwise.
        """
        result = await self.collection.delete_one(query)
        return result.deleted_count > 0

    @staticmethod
    def _convert_from_mongo_types(obj: Any) -> Any:
        """Recursively convert MongoDB types (like Decimal128) back to Python/Pydantic types."""
        from bson.decimal128 import Decimal128
        from decimal import Decimal

        if isinstance(obj, Decimal128):
            return obj.to_decimal()
        if isinstance(obj, dict):
            return {k: BaseRepository._convert_from_mongo_types(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [BaseRepository._convert_from_mongo_types(item) for item in obj]
        return obj

    def _from_mongo(self, raw: dict) -> T:
        """Convert a raw MongoDB document to a pydantic model instance."""
        if self._model_class is None:
            raise RuntimeError(
                f"Model class not set for {self.__class__.__name__}. "
                "Call _set_model_class() in the subclass constructor."
            )
        # Convert _id from ObjectId to string if needed
        if "_id" in raw and hasattr(raw["_id"], "__str__"):
            raw["_id"] = str(raw["_id"])
        
        # Convert Decimal128 back to Python Decimal
        raw = self._convert_from_mongo_types(raw)
        
        return self._model_class.model_validate(raw)

