"""Domain contracts for incremental ingestion checkpoint recovery."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Optional, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class CheckpointStatus(StrEnum):
    """Lifecycle of a scheduled or backfill checkpoint."""

    ABSENT = "ABSENT"
    DISCOVERED = "DISCOVERED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class IngestionMode(StrEnum):
    """Execution mode used to isolate scheduled streams from backfills."""

    SCHEDULED = "SCHEDULED"
    BACKFILL = "BACKFILL"


class IngestionCheckpoint(BaseModel):
    """Progress and recovery state for one logical ingestion stream."""

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: UUID = Field(default_factory=uuid4, alias="_id")
    partner: str
    fetch_config_id: str = Field(alias="fetchConfigId")
    source_type: str = Field(alias="sourceType")
    stream_key: str = Field(alias="streamKey")
    mode: IngestionMode = IngestionMode.SCHEDULED
    current_unit_key: Optional[str] = Field(default=None, alias="currentUnitKey")
    last_completed_unit_key: Optional[str] = Field(default=None, alias="lastCompletedUnitKey")
    cursor_before: Optional[str] = Field(default=None, alias="cursorBefore")
    cursor_after: Optional[str] = Field(default=None, alias="cursorAfter")
    high_water_mark: Optional[dict[str, Any]] = Field(default=None, alias="highWaterMark")
    status: CheckpointStatus = CheckpointStatus.ABSENT
    attempt_count: int = Field(default=0, alias="attemptCount", ge=0)
    claim_id: Optional[str] = Field(default=None, alias="claimId")
    last_error: Optional[str] = Field(default=None, alias="lastError")
    error_code: Optional[str] = Field(default=None, alias="errorCode")
    retryable: Optional[bool] = None
    next_retry_at: Optional[datetime] = Field(default=None, alias="nextRetryAt")
    blocked_at: Optional[datetime] = Field(default=None, alias="blockedAt")
    blocked_reason: Optional[str] = Field(default=None, alias="blockedReason")
    last_error_metadata: dict[str, Any] = Field(default_factory=dict, alias="lastErrorMetadata")
    resolution_metadata: dict[str, Any] = Field(default_factory=dict, alias="resolutionMetadata")
    started_at: Optional[datetime] = Field(default=None, alias="startedAt")
    completed_at: Optional[datetime] = Field(default=None, alias="completedAt")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="updatedAt")
    config_version: Optional[str] = Field(default=None, alias="configVersion")
    source_endpoint: Optional[str] = Field(default=None, alias="sourceEndpoint")
    stream_metadata: dict[str, Any] = Field(default_factory=dict, alias="streamMetadata")


class CheckpointRepository(Protocol):
    """Checkpoint operations required by source-unit orchestration."""

    async def claim_unit(
        self,
        *,
        partner: str,
        fetch_config_id: str,
        source_type: str,
        stream_key: str,
        unit_key: str,
        mode: IngestionMode = IngestionMode.SCHEDULED,
        cursor_before: Optional[str] = None,
        expected_previous_unit_key: Optional[str] = None,
        max_attempts: Optional[int] = None,
        config_version: Optional[str] = None,
        source_endpoint: Optional[str] = None,
        stream_metadata: Optional[dict[str, Any]] = None,
        claim_timeout_seconds: int = 900,
    ) -> tuple[IngestionCheckpoint, bool]: ...

    async def mark_failed(
        self,
        checkpoint: IngestionCheckpoint,
        *,
        unit_key: str,
        error: str,
        error_code: str = "source_unit_failed",
        retryable: bool = True,
        next_retry_at: Optional[datetime] = None,
        max_attempts: Optional[int] = None,
        error_metadata: Optional[dict[str, Any]] = None,
    ) -> bool: ...

    async def release_for_review(
        self,
        checkpoint: IngestionCheckpoint,
        *,
        unit_key: str,
        reason: str,
    ) -> bool: ...

    async def mark_completed(
        self,
        checkpoint: IngestionCheckpoint,
        *,
        unit_key: str,
        cursor_after: Optional[str] = None,
        high_water_mark: Optional[dict[str, Any]] = None,
    ) -> bool: ...

    async def advance(self, checkpoint: IngestionCheckpoint, *, unit_key: str) -> bool: ...
