"""Append-only audit event model and repository."""

from datetime import datetime, timezone
from typing import Any, Optional, Union
from uuid import UUID, uuid4

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.repository import BaseRepository


class AuditEvent(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: Union[UUID, str, ObjectId] = Field(default_factory=uuid4, alias="_id")
    entity_type: str = Field(alias="entityType")
    entity_id: str = Field(alias="entityId")
    action: str
    actor: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        alias="createdAt",
    )

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, v):
        if isinstance(v, ObjectId):
            return str(v)
        return v


class AuditEventRepository(BaseRepository[AuditEvent]):
    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="audit_event", db=db)
        self._set_model_class(AuditEvent)
