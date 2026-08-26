"""Domain contract for rejected ingestion rows."""

from dataclasses import dataclass
from enum import StrEnum
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class QuarantineStatus(StrEnum):
    PENDING = "PENDING"
    REPROCESSING = "REPROCESSING"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class QuarantineTransitionStatus(StrEnum):
    """Outcome of an optimistic quarantine state transition."""

    APPLIED = "APPLIED"
    REPLAYED = "REPLAYED"
    CONFLICT = "CONFLICT"
    NOT_FOUND = "NOT_FOUND"


@dataclass(frozen=True, slots=True)
class QuarantineTransitionResult:
    status: QuarantineTransitionStatus
    record: "IngestionQuarantineRecord | None" = None


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
    incoming_fingerprint: str | None = Field(default=None, alias="incomingFingerprint")
    existing_fingerprint: str | None = Field(default=None, alias="existingFingerprint")
    errors: list[dict[str, Any]] = Field(default_factory=list)
    phase: QuarantinePhase = QuarantinePhase.VALIDATION
    severity: QuarantineSeverity = QuarantineSeverity.RECORD
    config_version: str | None = Field(default=None, alias="configVersion")
    status: QuarantineStatus = QuarantineStatus.PENDING
    attempt_count: int = Field(default=1, alias="attemptCount", ge=1)
    expires_at: datetime | None = Field(default=None, alias="expiresAt")
    claimed_by: str | None = Field(default=None, alias="claimedBy", max_length=128)
    claimed_at: datetime | None = Field(default=None, alias="claimedAt")
    last_action_id: str | None = Field(default=None, alias="lastActionId", max_length=128)
    resolution_metadata: dict[str, Any] = Field(default_factory=dict, alias="resolutionMetadata")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="createdAt")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="updatedAt")


def sanitize_raw_row(value: Any, *, max_length: int = 512) -> Any:
    """Keep quarantine payload useful while masking obvious secret fields."""
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            normalized_key = "".join(character for character in key_text.lower() if character.isalnum())
            if any(
                token in normalized_key
                for token in ("password", "secret", "token", "apikey", "authorization", "credential")
            ):
                sanitized[key_text] = "[REDACTED]"
            else:
                sanitized[key_text] = sanitize_raw_row(item, max_length=max_length)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [sanitize_raw_row(item, max_length=max_length) for item in value]
    if isinstance(value, str) and len(value) > max_length:
        return f"{value[:max_length]}..."
    return value
