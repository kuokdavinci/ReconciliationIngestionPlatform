"""Domain model for reconciliation output."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.core.enums import ReconciliationStatus


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
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="createdAt"
    )
