"""Domain model for internal source-of-truth transactions."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.enums import TransactionStatus


class InternalTransaction(BaseModel):
    """Internal transaction used as the reconciliation source of truth."""

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: str = Field(alias="_id")
    partner: str
    partner_txn_id: str = Field(alias="partnerTxnId")
    amount: Decimal
    currency: str = "VND"
    status: TransactionStatus
    transaction_time: datetime = Field(alias="transactionTime")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="createdAt"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="updatedAt"
    )

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
