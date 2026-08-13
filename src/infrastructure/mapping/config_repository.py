"""MongoDB adapter for versioned mapping configurations."""

from datetime import datetime, timezone
import re
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from src.core.enums import FileType
from src.domain.mapping.models import MappingConfig, MappingConfigStatus
from src.infrastructure.persistence.mongo_repository import BaseRepository


class MappingConfigRepository(BaseRepository[MappingConfig]):
    """Persistence adapter for ``reconciliation_mapping_config``."""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="reconciliation_mapping_config", db=db)
        self._set_model_class(MappingConfig)
        self._version_counter_collection = db["reconciliation_mapping_config_version_counters"]

    async def find_by_partner_and_type(
        self, partner: str, workflow_type: str, file_type: FileType
    ) -> Optional[MappingConfig]:
        return await self.find_one(
            {
                "partner": partner,
                "workflowType": workflow_type,
                "fileType": file_type.value,
                "status": MappingConfigStatus.APPROVED.value,
            }
        )

    async def find_by_version(
        self, partner: str, version: str
    ) -> Optional[MappingConfig]:
        return await self.find_one(
            {
                "partner": partner,
                "configVersion": version,
                "status": MappingConfigStatus.APPROVED.value,
            }
        )

    async def find_latest_pending_by_partner_and_type(
        self, partner: str, workflow_type: str, file_type: FileType
    ) -> Optional[MappingConfig]:
        raw = await self.collection.find_one(
            {
                "partner": partner,
                "workflowType": workflow_type,
                "fileType": file_type.value,
                "status": MappingConfigStatus.PENDING_APPROVAL.value,
            },
            sort=[("createdAt", -1)],
        )
        if raw is None:
            return None
        return self._from_mongo(raw)

    async def allocate_next_version(self, partner: str) -> str:
        existing_counter = await self._version_counter_collection.find_one({"_id": partner})
        if existing_counter is None:
            max_version = await self._find_max_partner_version_number(partner)
            try:
                await self._version_counter_collection.insert_one(
                    {
                        "_id": partner,
                        "sequence": max_version,
                        "createdAt": datetime.now(timezone.utc),
                    }
                )
            except Exception:
                pass

        counter = await self._version_counter_collection.find_one_and_update(
            {"_id": partner},
            {
                "$inc": {"sequence": 1},
                "$set": {"updatedAt": datetime.now(timezone.utc)},
            },
            return_document=ReturnDocument.AFTER,
        )
        return f"{partner}_v{int(counter['sequence']):02d}"

    async def mark_superseded(
        self,
        config_id: str,
        superseded_by_config_id: str,
        superseded_at: datetime,
    ) -> bool:
        result = await self.collection.update_one(
            {"_id": str(config_id)},
            {
                "$set": {
                    "status": MappingConfigStatus.SUPERSEDED.value,
                    "supersededAt": superseded_at,
                    "supersededByConfigId": str(superseded_by_config_id),
                }
            },
        )
        return result.modified_count > 0

    async def mark_approved(
        self,
        config_id: str,
        approved_at: datetime,
        approved_by: str | None,
        config_health: dict[str, Any],
    ) -> bool:
        result = await self.collection.update_one(
            {"_id": str(config_id)},
            {
                "$set": {
                    "status": MappingConfigStatus.APPROVED.value,
                    "approvedAt": approved_at,
                    "approvedBy": approved_by,
                    "configHealth": config_health,
                }
            },
        )
        return result.modified_count > 0

    async def mark_rejected(
        self,
        config_id: str,
        config_health: dict[str, Any],
    ) -> bool:
        result = await self.collection.update_one(
            {"_id": str(config_id)},
            {
                "$set": {
                    "status": MappingConfigStatus.REJECTED.value,
                    "configHealth": config_health,
                }
            },
        )
        return result.modified_count > 0

    async def update_pending_draft(self, config_id: str, updates: dict[str, Any]) -> bool:
        result = await self.collection.update_one(
            {"_id": str(config_id), "status": MappingConfigStatus.PENDING_APPROVAL.value},
            {"$set": updates},
        )
        return result.modified_count > 0

    async def replace_approved(self, config: MappingConfig) -> MappingConfig:
        data = self._to_mongo(config)
        await self.collection.replace_one({"_id": data["_id"]}, data)
        return config

    async def insert_approved(self, config: MappingConfig) -> MappingConfig:
        await self.collection.insert_one(self._to_mongo(config))
        return config

    async def _find_max_partner_version_number(self, partner: str) -> int:
        cursor = self.collection.find(
            {
                "partner": partner,
                "configVersion": {"$regex": rf"^{re.escape(partner)}_v\d+$"},
            },
            projection={"configVersion": 1},
        )
        max_version = 0
        async for raw in cursor:
            version = raw.get("configVersion")
            if not isinstance(version, str):
                continue
            try:
                max_version = max(max_version, int(version.rsplit("v", 1)[1]))
            except (IndexError, ValueError):
                continue
        return max_version
