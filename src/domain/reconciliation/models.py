"""Domain models for reconciliation output and manually triggered reconciliation runs."""

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Union
from uuid import UUID, uuid4

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.enums import ReconciliationStatus


class ReconciliationRunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TimestampStatus(str, Enum):
    MATCHED = "MATCHED"
    MISMATCH = "MISMATCH"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    NOT_EVALUATED = "NOT_EVALUATED"


class ReconciliationRun(BaseModel):
    """State of a manual reconciliation run."""

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
    def normalize_id(cls, value):
        if isinstance(value, ObjectId):
            return str(value)
        return value


class ReconciliationResult(BaseModel):
    """Result produced by reconciliation matching."""

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: str = Field(alias="_id")
    partner: str = Field(alias="partner")
    date: str = Field(alias="date")
    partner_txn_id: str = Field(alias="partnerTxnId")
    reconciliation_key: Optional[str] = Field(default=None, alias="reconciliationKey")
    internal_txn_id: Optional[str] = Field(default=None, alias="internalTxnId")
    partner_amount: Optional[Decimal] = Field(default=None, alias="partnerAmount")
    internal_amount: Optional[Decimal] = Field(default=None, alias="internalAmount")
    partner_status: Optional[str] = Field(default=None, alias="partnerStatus")
    internal_status: Optional[str] = Field(default=None, alias="internalStatus")
    reconciliation_status: ReconciliationStatus = Field(alias="reconciliationStatus")
    reconciliation_run_id: Optional[str] = Field(default=None, alias="reconciliationRunId")
    source_file_id: Optional[str] = Field(default=None, alias="sourceFileId")
    scope_type: Optional[str] = Field(default=None, alias="scopeType")
    mapping_version: Optional[str] = Field(default=None, alias="mappingVersion")
    partner_record_id: Optional[str] = Field(default=None, alias="partnerRecordId")
    internal_record_id: Optional[str] = Field(default=None, alias="internalRecordId")
    partner_trans_date: Optional[datetime] = Field(default=None, alias="partnerTransDate")
    internal_transaction_time: Optional[datetime] = Field(
        default=None, alias="internalTransactionTime"
    )
    timestamp_status: TimestampStatus = Field(
        default=TimestampStatus.NOT_EVALUATED, alias="timestampStatus"
    )
    timestamp_delta_seconds: Optional[Decimal] = Field(
        default=None, alias="timestampDeltaSeconds"
    )
    timestamp_tolerance_seconds: Optional[int] = Field(
        default=None, alias="timestampToleranceSeconds"
    )
    timestamp_timezone: Optional[str] = Field(default=None, alias="timestampTimezone")
    timestamp_basis: str = Field(default="LEGACY_STORED", alias="timestampBasis")
    ambiguous_partner_record_ids: list[str] = Field(
        default_factory=list, alias="ambiguousPartnerRecordIds"
    )
    ambiguous_internal_record_ids: list[str] = Field(
        default_factory=list, alias="ambiguousInternalRecordIds"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="createdAt"
    )


__all__ = [
    "ReconciliationRunStatus",
    "TimestampStatus",
    "ReconciliationRun",
    "ReconciliationResult",
]
