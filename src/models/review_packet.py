"""Review packet model and repository for approval-desk workflows."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union
from uuid import UUID, uuid4

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from src.models.repository import BaseRepository


class ReviewPacketStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ReviewPacketSourceType(str, Enum):
    UPLOAD = "UPLOAD"
    SCHEDULER_JOB = "SCHEDULER_JOB"
    STUDIO_HANDOFF = "STUDIO_HANDOFF"


class ReviewDecisionMode(str, Enum):
    APPROVE_ACTIVATE_NEXT_RUNTIME = "APPROVE_ACTIVATE_NEXT_RUNTIME"
    APPROVE_KEEP_CURRENT_FOR_FILE = "APPROVE_KEEP_CURRENT_FOR_FILE"
    REJECT = "REJECT"
    SEND_TO_MAPPING_STUDIO = "SEND_TO_MAPPING_STUDIO"


class ReviewPacket(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: Union[UUID, str, ObjectId] = Field(default_factory=uuid4, alias="_id")
    source_type: ReviewPacketSourceType = Field(alias="sourceType")
    partner: str
    file_name: str = Field(alias="fileName")
    file_type_detected: str = Field(alias="fileTypeDetected")
    structure_signature: Optional[dict[str, Any]] = Field(default=None, alias="structureSignature")
    active_runtime_config_id: Optional[str] = Field(default=None, alias="activeRuntimeConfigId")
    draft_mapping_id: Optional[str] = Field(
        default=None,
        alias="draftMappingId",
        validation_alias=AliasChoices("draftMappingId", "proposalConfigId"),
    )
    target_action_id: Optional[str] = Field(default=None, alias="targetActionId")
    source_file_id: Optional[str] = Field(default=None, alias="sourceFileId")
    source_file_path: Optional[str] = Field(default=None, alias="sourceFilePath")
    scope_type: Optional[str] = Field(default=None, alias="scopeType")
    scope_confidence: Optional[float] = Field(default=None, alias="scopeConfidence")
    scope_reason: list[str] = Field(default_factory=list, alias="scopeReason")
    scope_signals: dict[str, Any] = Field(default_factory=dict, alias="scopeSignals")
    recommended_action: dict[str, Any] = Field(default_factory=dict, alias="recommendedAction")
    parse_strategy: dict[str, Any] = Field(default_factory=dict, alias="parseStrategy")
    validation_gates: list[dict[str, Any]] = Field(default_factory=list, alias="validationGates")
    sample_preview: list[dict[str, Any]] = Field(default_factory=list, alias="samplePreview")
    risk_summary: dict[str, Any] = Field(default_factory=dict, alias="riskSummary")
    runtime_decision_hint: Optional[str] = Field(default=None, alias="runtimeDecisionHint")
    status: ReviewPacketStatus = ReviewPacketStatus.PENDING
    decision_mode: Optional[ReviewDecisionMode] = Field(default=None, alias="decisionMode")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), alias="createdAt")
    reviewed_at: Optional[datetime] = Field(default=None, alias="reviewedAt")
    reviewed_by: Optional[str] = Field(default=None, alias="reviewedBy")

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, v):
        if isinstance(v, ObjectId):
            return str(v)
        return v


class ReviewPacketRepository(BaseRepository[ReviewPacket]):
    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="review_packet", db=db)
        self._set_model_class(ReviewPacket)

    async def find_latest_by_proposal(self, proposal_config_id: str) -> Optional[ReviewPacket]:
        raw = await self.collection.find_one(
            {"$or": [{"draftMappingId": proposal_config_id}, {"proposalConfigId": proposal_config_id}]},
            sort=[("createdAt", -1)],
        )
        if raw is None:
            return None
        return self._from_mongo(raw)
