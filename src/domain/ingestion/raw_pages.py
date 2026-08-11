"""Durable staging contract for large API source pages."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class RawPageStatus(StrEnum):
    STAGED = "STAGED"
    CONSUMED = "CONSUMED"
    FAILED = "FAILED"


class RawIngestionPage(BaseModel):
    """Mongo metadata for a raw page stored in GridFS.

    The payload is deliberately not embedded in this document: MongoDB BSON
    documents have a 16 MB limit and page payloads can be much larger.
    """

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: UUID = Field(default_factory=uuid4, alias="_id")
    stage_key: str = Field(alias="stageKey")
    partner: str
    fetch_config_id: str = Field(alias="fetchConfigId")
    source_type: str = Field(alias="sourceType")
    stream_key: str = Field(alias="streamKey")
    reconciliation_date: datetime = Field(alias="reconciliationDate")
    source_unit_key: str = Field(alias="sourceUnitKey")
    page: Optional[int] = None
    cursor_before: Optional[str] = Field(default=None, alias="cursorBefore")
    cursor_after: Optional[str] = Field(default=None, alias="cursorAfter")
    content_hash: Optional[str] = Field(default=None, alias="contentHash")
    content_type: Optional[str] = Field(default=None, alias="contentType")
    item_count: int = Field(default=0, alias="itemCount")
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    sample_rows: list[Any] = Field(default_factory=list, alias="sampleRows")
    gridfs_file_id: Any = Field(default=None, alias="gridfsFileId")
    local_path: Optional[str] = Field(default=None, alias="localPath")
    status: RawPageStatus = RawPageStatus.STAGED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="createdAt")
    consumed_at: Optional[datetime] = Field(default=None, alias="consumedAt")
    expires_at: Optional[datetime] = Field(default=None, alias="expiresAt")

