"""Domain contract for rejected ingestion rows."""

from enum import StrEnum
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QuarantineStatus(StrEnum):
    PENDING = "PENDING"
    REPROCESSING = "REPROCESSING"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class QuarantineAction(StrEnum):
    REPROCESS = "REPROCESS"
    ACCEPT_EXISTING = "ACCEPT_EXISTING"
    REJECT = "REJECT"
    ESCALATE = "ESCALATE"


class QuarantinePriority(StrEnum):
    NORMAL = "NORMAL"
    HIGH = "HIGH"


class QuarantineTransitionError(ValueError):
    """Raised when a quarantine record attempts an invalid state change."""


class QuarantinePhase(StrEnum):
    NORMALIZATION = "NORMALIZATION"
    VALIDATION = "VALIDATION"
    BATCH = "BATCH"


class QuarantineSeverity(StrEnum):
    RECORD = "RECORD"
    FATAL = "FATAL"


class QuarantineRetentionPolicy(BaseModel):
    """Explicit evidence windows for terminal quarantine records."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    resolved_days: int = Field(default=90, alias="resolvedDays", ge=1)
    rejected_days: int = Field(default=365, alias="rejectedDays", ge=1)
    sanitized_row_days: int = Field(default=30, alias="sanitizedRowDays", ge=1)

    def days_for(self, status: QuarantineStatus) -> int:
        if status is QuarantineStatus.RESOLVED:
            return self.resolved_days
        if status is QuarantineStatus.REJECTED:
            return self.rejected_days
        raise ValueError("Retention applies only to terminal quarantine statuses")


_ALLOWED_QUARANTINE_TRANSITIONS: dict[QuarantineStatus, frozenset[QuarantineStatus]] = {
    QuarantineStatus.PENDING: frozenset({QuarantineStatus.REPROCESSING}),
    QuarantineStatus.REPROCESSING: frozenset(
        {
            QuarantineStatus.PENDING,
            QuarantineStatus.RESOLVED,
            QuarantineStatus.REJECTED,
        }
    ),
    QuarantineStatus.RESOLVED: frozenset(),
    QuarantineStatus.REJECTED: frozenset(),
}


def assert_quarantine_transition(
    current: QuarantineStatus,
    target: QuarantineStatus,
) -> None:
    """Validate one explicit quarantine state transition."""
    if target not in _ALLOWED_QUARANTINE_TRANSITIONS[current]:
        raise QuarantineTransitionError(
            f"Invalid quarantine transition: {current.value} -> {target.value}"
        )


class QuarantineResolutionEvent(BaseModel):
    """Append-only evidence for one operator or worker transition."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    event_id: UUID = Field(default_factory=uuid4, alias="eventId")
    from_status: QuarantineStatus = Field(alias="fromStatus")
    to_status: QuarantineStatus = Field(alias="toStatus")
    action: QuarantineAction
    actor: str
    reason: str = Field(max_length=500)
    attempt: int = Field(ge=1)
    action_id: str | None = Field(default=None, alias="actionId", min_length=1, max_length=128)
    outcome: str | None = Field(default=None, max_length=128)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class QuarantineQuery(BaseModel):
    """Bounded filters shared by quarantine work queues and API reads."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    partner: str | None = None
    status: QuarantineStatus | None = None
    phase: QuarantinePhase | None = None
    error_code: str | None = Field(default=None, alias="errorCode")
    source_file_id: str | None = Field(default=None, alias="sourceFileId")
    source_unit_key: str | None = Field(default=None, alias="sourceUnitKey")
    claimed_by: str | None = Field(default=None, alias="claimedBy")
    priority: QuarantinePriority | None = None
    overdue: bool | None = None
    from_date: datetime | None = Field(default=None, alias="fromDate")
    to_date: datetime | None = Field(default=None, alias="toDate")
    limit: int = Field(default=100, ge=1, le=200)
    cursor: str | None = None


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
    ingestion_key: str | None = Field(default=None, alias="ingestionKey")
    incoming_fingerprint: str | None = Field(default=None, alias="incomingFingerprint")
    existing_fingerprint: str | None = Field(default=None, alias="existingFingerprint")
    errors: list[dict[str, Any]] = Field(default_factory=list)
    phase: QuarantinePhase = QuarantinePhase.VALIDATION
    severity: QuarantineSeverity = QuarantineSeverity.RECORD
    config_version: str | None = Field(default=None, alias="configVersion")
    status: QuarantineStatus = QuarantineStatus.PENDING
    priority: QuarantinePriority = QuarantinePriority.NORMAL
    review_due_at: datetime | None = Field(default=None, alias="reviewDueAt")
    escalation_level: int = Field(default=0, alias="escalationLevel", ge=0, le=3)
    escalated_at: datetime | None = Field(default=None, alias="escalatedAt")
    escalated_by: str | None = Field(default=None, alias="escalatedBy")
    last_action_id: str | None = Field(default=None, alias="lastActionId", min_length=1, max_length=128)
    attempt_count: int = Field(default=1, alias="attemptCount", ge=1)
    expires_at: datetime | None = Field(default=None, alias="expiresAt")
    claimed_by: str | None = Field(default=None, alias="claimedBy")
    claimed_at: datetime | None = Field(default=None, alias="claimedAt")
    claim_expires_at: datetime | None = Field(default=None, alias="claimExpiresAt")
    last_attempt_error: str | None = Field(default=None, alias="lastAttemptError")
    resolution_metadata: dict[str, Any] = Field(default_factory=dict, alias="resolutionMetadata")
    resolution_history: list[QuarantineResolutionEvent] = Field(
        default_factory=list,
        alias="resolutionHistory",
    )
    retention_until: datetime | None = Field(default=None, alias="retentionUntil")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="createdAt")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), alias="updatedAt")

    @model_validator(mode="after")
    def _set_operator_defaults(self) -> "IngestionQuarantineRecord":
        if self.severity is QuarantineSeverity.FATAL or any(
            isinstance(error, dict)
            and (
                error.get("errorCode")
                or error.get("error_code")
                or error.get("code")
            )
            == "CONFLICTING_DUPLICATE"
            for error in self.errors
        ):
            self.priority = QuarantinePriority.HIGH
        if self.review_due_at is None:
            from src.config.settings import settings

            self.review_due_at = self.created_at + timedelta(
                hours=settings.ingestion_quarantine_review_sla_hours
            )
        return self


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
