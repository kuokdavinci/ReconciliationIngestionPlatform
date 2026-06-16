"""Manual reconciliation run tracking for UI-triggered execution."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Union
from uuid import UUID, uuid4

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.repository import BaseRepository


class ReconciliationRunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ReconciliationRun(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: Union[UUID, str, ObjectId] = Field(default_factory=uuid4, alias="_id")
    partner: str
    date: str
    status: ReconciliationRunStatus = ReconciliationRunStatus.QUEUED
    message: Optional[str] = None
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


class ReconciliationRunRepository(BaseRepository[ReconciliationRun]):
    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="reconciliation_run", db=db)
        self._set_model_class(ReconciliationRun)

    async def find_latest_by_partner_and_date(self, partner: str, date: str) -> Optional[ReconciliationRun]:
        raw = await self.collection.find_one(
            {"partner": partner, "date": date},
            sort=[("createdAt", -1)],
        )
        if raw is None:
            return None
        return self._from_mongo(raw)
