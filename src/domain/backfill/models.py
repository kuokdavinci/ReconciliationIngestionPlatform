"""Domain models for durable backfill orchestration state."""

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Optional, Union
from uuid import UUID, uuid4

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.domain.ingestion.checkpoints import IngestionMode
from src.domain.runtime.models import RuntimeOrchestrationContext


class BackfillRunStatus(StrEnum):
    WAITING_CONFIG = "WAITING_CONFIG"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class BackfillDayStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    WAITING_CONFIG = "WAITING_CONFIG"


class BackfillApprovalContext(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    workflow_type: str = Field(alias="workflowType")
    file_type: str = Field(alias="fileType")
    review_packet_id: Optional[str] = Field(default=None, alias="reviewPacketId")
    reason: Optional[str] = None


class BackfillDayRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    business_date: date = Field(alias="businessDate")
    status: BackfillDayStatus = BackfillDayStatus.PENDING
    runtime_run_id: Optional[str] = Field(default=None, alias="runtimeRunId")
    message: Optional[str] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="updatedAt")


class BackfillRun(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: Union[UUID, str, ObjectId] = Field(default_factory=uuid4, alias="_id")
    partner: str
    fetch_config_id: str = Field(alias="fetchConfigId")
    mode: IngestionMode = IngestionMode.BACKFILL
    status: BackfillRunStatus
    from_date: date = Field(alias="fromDate")
    to_date: date = Field(alias="toDate")
    current_date: Optional[date] = Field(default=None, alias="currentDate")
    completed_days: int = Field(default=0, alias="completedDays", ge=0)
    total_days: int = Field(alias="totalDays", ge=0)
    config_version: Optional[str] = Field(default=None, alias="configVersion")
    mapping_version: Optional[str] = Field(default=None, alias="mappingVersion")
    approval_required: bool = Field(default=False, alias="approvalRequired")
    approval_context: Optional[BackfillApprovalContext] = Field(default=None, alias="approvalContext")
    orchestration: Optional[RuntimeOrchestrationContext] = None
    days: list[BackfillDayRecord] = Field(default_factory=list)
    triggered_by: Optional[str] = Field(default=None, alias="triggeredBy")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="createdAt")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="updatedAt")

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, value):
        if isinstance(value, ObjectId):
            return str(value)
        return value
