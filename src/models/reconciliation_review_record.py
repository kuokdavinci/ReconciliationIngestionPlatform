"""Persistence model for reconciliation review notes and resolution state."""

from datetime import datetime, timezone
from typing import Optional, Union
from uuid import UUID, uuid4

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.repository import BaseRepository


class ReconciliationReviewNote(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    time: str
    event: str


class ReconciliationReviewRecord(BaseModel):
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
    def normalize_id(cls, v):
        if isinstance(v, ObjectId):
            return str(v)
        return v


class ReconciliationReviewRecordRepository(BaseRepository[ReconciliationReviewRecord]):
    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="reconciliation_review_record", db=db)
        self._set_model_class(ReconciliationReviewRecord)

    async def find_by_partner_and_date(self, partner: str, date: str) -> list[ReconciliationReviewRecord]:
        return await self.find_many({"partner": partner, "date": date})
