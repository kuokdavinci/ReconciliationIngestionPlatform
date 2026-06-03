"""MappingConfig model and repository for dynamic parsing configuration."""

from datetime import datetime, timezone
from typing import Any, Optional, Union
from uuid import UUID, uuid4

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.enums import FileType
from src.core.types import FieldMapping
from src.models.repository import BaseRepository


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

    async def find_by_partner_and_type(
        self, partner: str, workflow_type: str, file_type: FileType
    ) -> Optional[MappingConfig]:
        """Find the active mapping config for a partner/workflow/file_type."""
        return await self.find_one(
            {
                "partner": partner,
                "workflowType": workflow_type,
                "fileType": file_type.value,
            }
        )

    async def find_by_version(
        self, partner: str, version: str
    ) -> Optional[MappingConfig]:
        """Find a mapping config by partner and version identifier."""
        return await self.find_one(
            {"partner": partner, "configVersion": version}
        )
