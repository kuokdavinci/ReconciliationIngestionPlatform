"""Domain model for versioned partner mapping configuration."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.core.enums import FileType
from src.core.types import FieldMapping
from src.config.settings import settings


class MappingConfigStatus(str, Enum):
    APPROVED = "APPROVED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ReconciliationPolicy(BaseModel):
    """Versioned timestamp interpretation and evidence policy."""

    model_config = ConfigDict(populate_by_name=True)

    timestamp_tolerance_seconds: int = Field(
        default=300, alias="timestampToleranceSeconds", ge=0
    )
    timestamp_timezone: str = Field(
        default_factory=lambda: settings.business_timezone,
        alias="timestampTimezone",
    )

    @field_validator("timestamp_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid timestamp timezone: {value!r}") from exc
        return value


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
    reconciliation_policy: ReconciliationPolicy = Field(
        default_factory=ReconciliationPolicy, alias="reconciliationPolicy"
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

    @model_validator(mode="before")
    @classmethod
    def accept_timestamp_policy_alias(cls, value: Any) -> Any:
        if isinstance(value, dict):
            value = dict(value)
            policy = value.get("reconciliationPolicy") or value.get("timestampPolicy")
            if policy is None and "timestamp_policy" in value:
                policy = value["timestamp_policy"]
            flat_policy = {
                key: value[key]
                for key in ("timestampToleranceSeconds", "timestampTimezone")
                if key in value
            }
            if policy is None and flat_policy:
                policy = flat_policy
            if policy is not None:
                value["reconciliationPolicy"] = policy
        return value

    @property
    def timestamp_policy(self) -> ReconciliationPolicy:
        """Compatibility name used by ingestion and reconciliation call paths."""

        return self.reconciliation_policy

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, value):
        """Accept UUID, ObjectId, or string for the document id."""

        if isinstance(value, ObjectId):
            return str(value)
        return value
