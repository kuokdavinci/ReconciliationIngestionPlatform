"""Domain model for an ingestion file claim."""

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.core.enums import FileType, ProcessingStatus, ReconciliationScopeType


class ReconciliationFile(BaseModel):
    """File claim and processing state owned by the ingestion bounded context."""

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: UUID = Field(default_factory=uuid4, alias="_id")
    partner: str
    file_name: str = Field(alias="fileName")
    file_hash: str = Field(alias="fileHash")
    file_type: FileType = Field(alias="fileType")
    reconciliation_date: datetime = Field(alias="reconciliationDate")
    processing_status: ProcessingStatus = Field(
        default=ProcessingStatus.PENDING, alias="processingStatus"
    )
    total_rows: int = Field(default=0, alias="totalRows")
    success_rows: int = Field(default=0, alias="successRows")
    failed_rows: int = Field(default=0, alias="failedRows")
    duplicate_rows: int = Field(default=0, alias="duplicateRows")
    stage_summary: dict[str, Any] = Field(default_factory=dict, alias="stageSummary")
    config_version: Optional[str] = Field(default=None, alias="configVersion")
    fetch_unit_key: Optional[str] = Field(default=None, alias="fetchUnitKey")
    fetch_unit_metadata: dict = Field(default_factory=dict, alias="fetchUnitMetadata")
    source_file_path: Optional[str] = Field(default=None, alias="sourceFilePath")
    scope_type: ReconciliationScopeType = Field(
        default=ReconciliationScopeType.UNCONFIRMED,
        alias="scopeType",
    )
    scope_confidence: float = Field(default=0.0, alias="scopeConfidence")
    scope_reason: list[str] = Field(default_factory=list, alias="scopeReason")
    scope_signals: dict = Field(default_factory=dict, alias="scopeSignals")
    uploaded_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="uploadedAt"
    )
    created_by: str = Field(default="system", alias="createdBy")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="createdAt"
    )
