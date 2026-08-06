"""Domain contract for rejected ingestion rows."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class QuarantineStatus(StrEnum):
    PENDING = "PENDING"
    REPROCESSING = "REPROCESSING"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class QuarantinePhase(StrEnum):
    NORMALIZATION = "NORMALIZATION"
    VALIDATION = "VALIDATION"
    BATCH = "BATCH"


class QuarantineSeverity(StrEnum):
    RECORD = "RECORD"
    FATAL = "FATAL"


class IngestionQuarantineRecord(BaseModel):
    """Audit-friendly record for one rejected source row."""

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: UUID = Field(default_factory=uuid4, alias="_id")
    source_file_id: str = Field(alias="sourceFileId")
    source_unit_key: str | None = Field(default=None, alias="sourceUnitKey")
    partner: str
    reconciliation_date: datetime = Field(alias="reconciliationDate")
    row_number: int | None = Field(default=None, alias="rowNumber")
    raw_row: Any = Field(default_factory=dict, alias="rawRow")
    errors: list[dict[str, Any]] = Field(default_factory=list)
    phase: QuarantinePhase = QuarantinePhase.VALIDATION
    severity: QuarantineSeverity = QuarantineSeverity.RECORD
    config_version: str | None = Field(default=None, alias="configVersion")
    status: QuarantineStatus = QuarantineStatus.PENDING
    attempt_count: int = Field(default=1, alias="attemptCount", ge=1)
    resolution_metadata: dict[str, Any] = Field(
        default_factory=dict, alias="resolutionMetadata"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="createdAt")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="updatedAt")


def sanitize_raw_row(value: Any, *, max_length: int = 512) -> Any:
    """Keep quarantine payload useful while masking obvious secret fields."""
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(token in key_text.lower() for token in ("password", "secret", "token", "api_key")):
                sanitized[key_text] = "[REDACTED]"
            else:
                sanitized[key_text] = sanitize_raw_row(item, max_length=max_length)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [sanitize_raw_row(item, max_length=max_length) for item in value]
    if isinstance(value, str) and len(value) > max_length:
        return f"{value[:max_length]}..."
    return value
