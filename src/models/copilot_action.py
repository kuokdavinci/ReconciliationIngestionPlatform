"""Copilot action model and repository for human approval workflows."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union
from uuid import UUID, uuid4

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from src.core.enums import FileType
from src.models.repository import BaseRepository


class CopilotActionType(str, Enum):
    MAPPING_PROPOSAL = "MAPPING_PROPOSAL"
    PIPELINE_REVIEW = "PIPELINE_REVIEW"
    RECON_INSIGHT_ACTION = "RECON_INSIGHT_ACTION"


class CopilotActionStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISMISSED = "DISMISSED"


class CopilotAction(BaseModel):
    """A structured, reviewable AI artifact."""

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: Union[UUID, str, ObjectId] = Field(default_factory=uuid4, alias="_id")
    type: CopilotActionType
    status: CopilotActionStatus = CopilotActionStatus.PENDING_APPROVAL
    partner: str
    workflow_type: Optional[str] = Field(default=None, alias="workflowType")
    file_type: Optional[FileType] = Field(default=None, alias="fileType")
    draft_mapping_id: Optional[str] = Field(
        default=None,
        alias="draftMappingId",
        validation_alias=AliasChoices("draftMappingId", "targetConfigId"),
    )
    target_entity_id: Optional[str] = Field(default=None, alias="targetEntityId")
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="createdAt"
    )
    reviewed_at: Optional[datetime] = Field(default=None, alias="reviewedAt")
    reviewed_by: Optional[str] = Field(default=None, alias="reviewedBy")

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, v):
        if isinstance(v, ObjectId):
            return str(v)
        return v


class CopilotActionRepository(BaseRepository[CopilotAction]):
    """Repository for copilot approval items."""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="copilot_action", db=db)
        self._set_model_class(CopilotAction)
