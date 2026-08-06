"""Domain models for approval reprocessing and reconciliation review."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union
from uuid import UUID, uuid4

from bson import ObjectId
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from src.core.enums import FileType


class PostApprovalRunStatus(str, Enum):
    QUEUED = "QUEUED"
    INGESTING = "INGESTING"
    RECONCILING = "RECONCILING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PostApprovalRunStage(str, Enum):
    APPROVAL = "approval"
    INGESTION = "ingestion"
    RECONCILIATION = "reconciliation"
    CACHE_INVALIDATION = "cache_invalidation"


class PostApprovalRun(BaseModel):
    """State of a long-running reprocess and reconciliation workflow."""

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: Union[UUID, str, ObjectId] = Field(default_factory=uuid4, alias="_id")
    packet_id: str = Field(alias="packetId")
    partner: str
    date: Optional[str] = None
    status: PostApprovalRunStatus = PostApprovalRunStatus.QUEUED
    stage: PostApprovalRunStage = PostApprovalRunStage.APPROVAL
    message: Optional[str] = None
    source_file_id: Optional[str] = Field(default=None, alias="sourceFileId")
    output_file_id: Optional[str] = Field(default=None, alias="outputFileId")
    reconciliation_count: Optional[int] = Field(default=None, alias="reconciliationCount")
    stats: dict[str, Any] = Field(default_factory=dict)
    errors: list[Any] = Field(default_factory=list)
    started_at: Optional[datetime] = Field(default=None, alias="startedAt")
    finished_at: Optional[datetime] = Field(default=None, alias="finishedAt")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), alias="createdAt")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), alias="updatedAt")

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, value):
        if isinstance(value, ObjectId):
            return str(value)
        return value


class ReconciliationReviewNote(BaseModel):
    """An append-only note attached to a reconciliation review record."""

    model_config = ConfigDict(populate_by_name=True)

    time: str
    event: str


class ReconciliationReviewRecord(BaseModel):
    """Review resolution state for one reconciliation record."""

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: Union[UUID, str, ObjectId] = Field(default_factory=uuid4, alias="_id")
    partner: str
    date: str
    record_key: str = Field(alias="recordKey")
    reviewed: bool = False
    resolved_status: Optional[str] = Field(default=None, alias="resolvedStatus")
    notes: list[ReconciliationReviewNote] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), alias="createdAt")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), alias="updatedAt")

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, value):
        if isinstance(value, ObjectId):
            return str(value)
        return value


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
    """Approval-desk packet containing mapping and validation evidence."""

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
    draft_mapping_version: Optional[str] = Field(default=None, alias="draftMappingVersion")
    target_action_id: Optional[str] = Field(default=None, alias="targetActionId")
    source_file_id: Optional[str] = Field(default=None, alias="sourceFileId")
    source_file_path: Optional[str] = Field(default=None, alias="sourceFilePath")
    reconciliation_date: Optional[datetime] = Field(default=None, alias="reconciliationDate")
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
    def normalize_id(cls, value):
        if isinstance(value, ObjectId):
            return str(value)
        return value


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
    """Structured, reviewable AI artifact for approval workflows."""

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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), alias="createdAt")
    reviewed_at: Optional[datetime] = Field(default=None, alias="reviewedAt")
    reviewed_by: Optional[str] = Field(default=None, alias="reviewedBy")

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, value):
        if isinstance(value, ObjectId):
            return str(value)
        return value
