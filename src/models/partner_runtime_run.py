"""Unified runtime visibility model for fetch/ingest/reconcile flows."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union
from uuid import UUID, uuid4

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.repository import BaseRepository


class PartnerRuntimeTriggerType(str, Enum):
    SCHEDULER = "SCHEDULER"
    MANUAL_RECONCILIATION = "MANUAL_RECONCILIATION"
    POST_APPROVAL_REPROCESS = "POST_APPROVAL_REPROCESS"


class PartnerRuntimeRunStatus(str, Enum):
    QUEUED = "QUEUED"
    FETCHING = "FETCHING"
    INGESTING = "INGESTING"
    WAITING_REVIEW = "WAITING_REVIEW"
    WAITING_RECONCILE = "WAITING_RECONCILE"
    RECONCILING = "RECONCILING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PartnerRuntimeRun(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: Union[UUID, str, ObjectId] = Field(default_factory=uuid4, alias="_id")
    partner: str
    date: str
    trigger_type: PartnerRuntimeTriggerType = Field(alias="triggerType")
    triggered_by: Optional[str] = Field(default=None, alias="triggeredBy")
    status: PartnerRuntimeRunStatus = PartnerRuntimeRunStatus.QUEUED
    message: Optional[str] = None
    source_file_id: Optional[str] = Field(default=None, alias="sourceFileId")
    file_name: Optional[str] = Field(default=None, alias="fileName")
    mapping_version: Optional[str] = Field(default=None, alias="mappingVersion")
    validation_state: Optional[str] = Field(default=None, alias="validationState")
    stats: dict[str, Any] = Field(default_factory=dict)
    reconciliation_count: Optional[int] = Field(default=None, alias="reconciliationCount")
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


class PartnerRuntimeRunRepository(BaseRepository[PartnerRuntimeRun]):
    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="partner_runtime_run", db=db)
        self._set_model_class(PartnerRuntimeRun)

    async def find_latest_by_partner_and_date(self, partner: str, date: str) -> Optional[PartnerRuntimeRun]:
        raw = await self.collection.find_one(
            {"partner": partner, "date": date},
            sort=[("createdAt", -1)],
        )
        if raw is None:
            return None
        return self._from_mongo(raw)

    async def find_latest_by_partner(self, partner: str) -> Optional[PartnerRuntimeRun]:
        raw = await self.collection.find_one(
            {"partner": partner},
            sort=[("createdAt", -1)],
        )
        if raw is None:
            return None
        return self._from_mongo(raw)
