"""MongoDB adapter for versioned mapping configurations."""

from datetime import datetime, timezone
import re
from typing import Optional

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
