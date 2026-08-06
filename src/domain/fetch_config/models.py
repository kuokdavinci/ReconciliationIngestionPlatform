"""Domain models for partner data fetch scheduling."""

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
    password: str
    remote_path: str = Field(alias="remotePath")
    timeout: int = 30
    download_dir: Optional[str] = Field(default="./downloads", alias="downloadDir")


class APIConfig(BaseModel):
    """Configuration for API fetch method."""

    model_config = ConfigDict(populate_by_name=True)

    base_url: str = Field(alias="baseUrl")
    method: str = "GET"
    headers: Optional[dict[str, str]] = None
    query_params: Optional[dict[str, str]] = Field(default=None, alias="queryParams")
    timeout: int = 30
    download_dir: Optional[str] = Field(default="./downloads", alias="downloadDir")
class FileDropConfig(BaseModel):
    """Configuration for FileDrop fetch method."""

    model_config = ConfigDict(populate_by_name=True)

    directory: str
    pattern: str = "*.xlsx"


class FetchConfig(BaseModel):
    """Configuration for fetching partner data via SFTP, API or FileDrop."""

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: UUID = Field(default_factory=uuid4, alias="_id")
    partner: str
    fetch_method: FetchMethod = Field(alias="fetchMethod")
    enabled: bool = True
    schedule: str = "0 0 * * *"
    local_download_dir: str = Field(default="./downloads", alias="localDownloadDir")
    cleanup_after_ingest: bool = Field(default=True, alias="cleanupAfterIngest")
    archive_dir: Optional[str] = Field(default=None, alias="archiveDir")
    archive_retention_days: int = Field(default=30, alias="archiveRetentionDays")
    sftp: Optional[SFTPConfig] = None
    api: Optional[APIConfig] = None
    filedrop: Optional[FileDropConfig] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="createdAt")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="updatedAt")

    def get_method_config(self) -> Any:
        """Return the method-specific configuration selected by ``fetch_method``."""

        if self.fetch_method == FetchMethod.SFTP:
            return self.sftp
        if self.fetch_method == FetchMethod.API:
            return self.api
        if self.fetch_method == FetchMethod.FILEDROP:
            return self.filedrop
        return None
