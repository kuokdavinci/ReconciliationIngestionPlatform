"""MappingConfig model and repository for dynamic parsing configuration."""

from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Optional, Union
from uuid import UUID, uuid4

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.enums import FileType
from src.core.types import FieldMapping
from src.models.repository import BaseRepository


class MappingConfigStatus(str, Enum):
    APPROVED = "APPROVED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class MappingConfig(BaseModel):
    """Dynamic parsing configuration for a partner/workflow/file_type combination.

    The field_mappings array defines how source columns map to canonical fields,
    including transformations, constants, and status normalization rules.

    The structure_signature field stores a fingerprint of the file format at the
    time the config was created. It is used by ConfigHealthService to detect
    when a partner's file structure has changed (stale config).
    """

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: Union[UUID, str, ObjectId] = Field(default_factory=uuid4, alias="_id")
    partner: str
    workflow_type: str = Field(alias="workflowType")
    file_type: FileType = Field(alias="fileType")
    sheet_name: str = Field(alias="sheetName")
    start_row: int = Field(default=2, alias="startRow")
    field_mappings: list[FieldMapping] = Field(alias="fieldMappings")
    config_version: Optional[str] = Field(default=None, alias="configVersion")
    structure_signature: Optional[dict[str, Any]] = Field(
        default=None, alias="structureSignature"
    )
    config_health: Optional[dict[str, Any]] = Field(
        default=None, alias="configHealth"
    )
    status: MappingConfigStatus = MappingConfigStatus.APPROVED
    approved_at: Optional[datetime] = Field(default=None, alias="approvedAt")
    approved_by: Optional[str] = Field(default=None, alias="approvedBy")
    superseded_at: Optional[datetime] = Field(default=None, alias="supersededAt")
    superseded_by_config_id: Optional[str] = Field(
        default=None, alias="supersededByConfigId"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="createdAt"
    )

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, v):
        """Accept UUID, ObjectId, or string for _id field."""
        if isinstance(v, ObjectId):
            return str(v)
        return v


class MappingConfigRepository(BaseRepository[MappingConfig]):
    """Repository for MappingConfig with domain-specific query methods."""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="reconciliation_mapping_config", db=db)
        self._set_model_class(MappingConfig)
        self._version_counter_collection = db["reconciliation_mapping_config_version_counters"]

    async def find_by_partner_and_type(
        self, partner: str, workflow_type: str, file_type: FileType
    ) -> Optional[MappingConfig]:
        """Find the active mapping config for a partner/workflow/file_type."""
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
        """Find a mapping config by partner and version identifier."""
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
