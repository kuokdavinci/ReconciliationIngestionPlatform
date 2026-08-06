"""Domain model for versioned partner mapping configuration."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union
from uuid import UUID, uuid4

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.enums import FileType
from src.core.types import FieldMapping


class MappingConfigStatus(str, Enum):
    APPROVED = "APPROVED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class MappingConfig(BaseModel):
    """Versioned parsing configuration for a partner/workflow/file type."""

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
    def normalize_id(cls, value):
        """Accept UUID, ObjectId, or string for the document id."""

        if isinstance(value, ObjectId):
            return str(value)
        return value
