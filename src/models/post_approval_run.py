"""Post-approval run tracking for long-running reprocess + reconcile flows."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union
from uuid import UUID, uuid4

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.repository import BaseRepository


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
    def normalize_id(cls, v):
        if isinstance(v, ObjectId):
            return str(v)
        return v


class PostApprovalRunRepository(BaseRepository[PostApprovalRun]):
    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="post_approval_run", db=db)
        self._set_model_class(PostApprovalRun)

    async def find_latest_by_packet_id(self, packet_id: str) -> Optional[PostApprovalRun]:
        raw = await self.collection.find_one(
            {"packetId": packet_id},
            sort=[("createdAt", -1)],
        )
        if raw is None:
            return None
        return self._from_mongo(raw)
