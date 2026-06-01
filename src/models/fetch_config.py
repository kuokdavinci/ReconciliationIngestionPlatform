"""FetchConfig model and repository for partner data fetch scheduling.

Defines configuration models for different fetch methods (SFTP, API, FileDrop)
and provides repository for CRUD operations.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class FetchMethod(StrEnum):
    """Supported data fetch methods."""

    SFTP = "SFTP"
    API = "API"
    FILEDROP = "FILEDROP"


class SFTPConfig(BaseModel):
    """Configuration for SFTP fetch method."""

    model_config = ConfigDict(populate_by_name=True)

    host: str
    port: int = 22
    username: str
    password: str  # Can be plain text, env:VAR, or encrypted:VALUE
    remote_path: str = Field(alias="remotePath")
    timeout: int = 30


class APIConfig(BaseModel):
    """Configuration for API fetch method."""

    model_config = ConfigDict(populate_by_name=True)

    base_url: str = Field(alias="baseUrl")
    method: str = "GET"
    headers: Optional[dict[str, str]] = None
    query_params: Optional[dict[str, str]] = Field(
        default=None, alias="queryParams"
    )
    timeout: int = 30


class FileDropConfig(BaseModel):
    """Configuration for FileDrop fetch method."""

    model_config = ConfigDict(populate_by_name=True)

    directory: str
    pattern: str = "*.xlsx"


class FetchConfig(BaseModel):
    """Configuration for fetching partner data.

    Supports three fetch methods: SFTP, API, and FileDrop.
    Credentials can be stored as plain text, environment variable references
    (env:VAR_NAME), or encrypted values (encrypted:VALUE).
    """

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: UUID = Field(default_factory=uuid4, alias="_id")
    partner: str
    fetch_method: FetchMethod = Field(alias="fetchMethod")
    enabled: bool = True
    schedule: str = "0 0 * * *"  # Cron expression (default: daily at 00:00)
    local_download_dir: str = Field(
        default="./downloads", alias="localDownloadDir"
    )
    cleanup_after_ingest: bool = Field(
        default=True, alias="cleanupAfterIngest"
    )
    archive_dir: Optional[str] = Field(default=None, alias="archiveDir")
    archive_retention_days: int = Field(
        default=30, alias="archiveRetentionDays"
    )

    # Method-specific configurations (only one should be populated)
    sftp: Optional[SFTPConfig] = None
    api: Optional[APIConfig] = None
    filedrop: Optional[FileDropConfig] = None

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), alias="createdAt"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), alias="updatedAt"
    )

    def get_method_config(self) -> Any:
        """Get the configuration for the active fetch method."""
        if self.fetch_method == FetchMethod.SFTP:
            return self.sftp
        elif self.fetch_method == FetchMethod.API:
            return self.api
        elif self.fetch_method == FetchMethod.FILEDROP:
            return self.filedrop
        return None


class FetchConfigRepository:
    """Repository for FetchConfig CRUD operations."""

    def __init__(self, db):
        self._collection = db["fetch_config"]

    async def create(self, config: FetchConfig) -> FetchConfig:
        """Insert a new fetch config into the database."""
        doc = config.model_dump(by_alias=True, exclude_none=False)
        await self._collection.insert_one(doc)
        return config

    async def find_by_partner(self, partner: str) -> Optional[FetchConfig]:
        """Find fetch config by partner name."""
        raw = await self._collection.find_one({"partner": partner})
        if raw is None:
            return None
        return self._from_mongo(raw)

    async def find_enabled(self) -> list[FetchConfig]:
        """Find all enabled fetch configs."""
        cursor = self._collection.find({"enabled": True})
        results = []
        async for raw in cursor:
            results.append(self._from_mongo(raw))
        return results

    async def update(self, config: FetchConfig) -> bool:
        """Update an existing fetch config."""
        config.updated_at = datetime.now(UTC)
        doc = config.model_dump(by_alias=True, exclude_none=False)
        result = await self._collection.update_one(
            {"_id": config.id}, {"$set": doc}
        )
        return result.modified_count > 0

    async def delete_by_partner(self, partner: str) -> bool:
        """Delete fetch config by partner name."""
        result = await self._collection.delete_one({"partner": partner})
        return result.deleted_count > 0

    @staticmethod
    def _from_mongo(raw: dict) -> FetchConfig:
        """Convert raw MongoDB document to FetchConfig model."""
        if "_id" in raw and hasattr(raw["_id"], "__str__"):
            raw["_id"] = str(raw["_id"])
        return FetchConfig.model_validate(raw)
