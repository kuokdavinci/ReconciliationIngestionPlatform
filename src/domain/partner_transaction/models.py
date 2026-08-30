"""Domain models for canonical normalized partner transactions."""

from datetime import datetime, timezone
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PartnerData(BaseModel):
    """Normalized partner payload embedded in a canonical transaction."""

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: str = Field(alias="_id")
    trace: Optional[str] = None
    status: str
    amount: Decimal
    currency: str
    trans_date: Optional[datetime] = Field(default=None, alias="transDate")
    timestamp_basis: str = Field(default="LEGACY_STORED", alias="timestampBasis")
    extra: dict[str, Any] = {}

    @field_validator("amount", mode="before")
    @classmethod
    def reject_float(cls, value: Any) -> Any:
        """Reject float amounts to preserve monetary precision."""

        if isinstance(value, float):
            raise ValueError(
                "amount must be Decimal, int, or str — float is not allowed "
                "for monetary values to avoid precision errors"
            )
        return value


@dataclass(slots=True)
class FastPartnerData:
    """Lightweight partner payload used by the ingestion fast path."""

    id: str
    trace: Optional[str]
    status: str
    amount: Decimal
    currency: str
    trans_date: Optional[datetime]
    extra: dict[str, Any]
    timestamp_basis: str = "LEGACY_STORED"


@dataclass(slots=True)
class FastDataContainer:
    """Unvalidated, repository-ready transaction for fast ingestion."""

    id: UUID
    request_id: UUID
    identify: str
    workflow_type: str
    reconciliation_date: datetime
    operation_status: str
    reconciliation_status: str
    connector_data: str
    extra_data: str
    source_file_id: UUID
    ingestion_key: str
    partner_data: FastPartnerData
    created_by: str
    created_date: datetime
    last_modified_by: str
    last_modified_date: datetime


class DataContainer(BaseModel):
    """Canonical normalized partner transaction."""

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: UUID = Field(default_factory=uuid4, alias="_id")
    request_id: UUID = Field(default_factory=uuid4, alias="requestId")
    identify: str
    workflow_type: str = Field(alias="workflowType")
    reconciliation_date: datetime = Field(alias="reconciliationDate")
    operation_status: str = Field(default="IN_PROGRESS", alias="operationStatus")
    reconciliation_status: str = Field(default="", alias="reconciliationStatus")
    connector_data: str = Field(default="", alias="connectorData")
    extra_data: str = Field(default="", alias="extraData")
    source_file_id: UUID = Field(alias="sourceFileId")
    ingestion_key: str = Field(default="", alias="ingestionKey")
    partner_data: PartnerData = Field(alias="partnerData")
    created_by: str = Field(default="system", alias="createdBy")
    created_date: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="createdDate"
    )
    last_modified_by: str = Field(default="system", alias="lastModifiedBy")
    last_modified_date: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        alias="lastModifiedDate",
    )
