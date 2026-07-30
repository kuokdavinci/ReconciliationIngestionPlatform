"""Core canonical types for the reconciliation ingestion platform."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Optional, Union

from pydantic import BaseModel, field_validator

from src.core.enums import TransactionStatus


class FieldMappingType(StrEnum):
    """Type of field mapping transformation."""

    STRING = "STRING"
    DECIMAL = "DECIMAL"
    DATE = "DATE"
    CONSTANT = "CONSTANT"
    MAPPING = "MAPPING"


class FieldMapping(BaseModel):
    """Configuration for mapping a source field to a canonical field.

    column: 1-based column number from the Excel file (e.g., 1 = column A, 2 = column B).
    sourceField: optional human-readable field name for documentation.
    """

    path: str
    column: Optional[Union[int, str]] = None
    sourceField: Optional[str] = None
    type: FieldMappingType
    required: bool = False
    constant: Optional[str] = None
    mapping: Optional[dict[str, str]] = None


class CanonicalTransaction(BaseModel):
    """Canonical transaction model — the normalized output of ingestion.

    Monetary amounts use Decimal exclusively — floats are rejected to
    prevent floating-point precision errors in financial calculations.
    """

    id: str
    trace: Optional[str] = None
    amount: Decimal
    currency: str
    status: TransactionStatus
    transDate: Optional[datetime] = None
    extra: dict[str, Any] = {}

    @field_validator("amount", mode="before")
    @classmethod
    def reject_float(cls, v: Any) -> Any:
        """Reject float values for amount — must be Decimal, int, or str."""
        if isinstance(v, float):
            raise ValueError(
                "amount must be Decimal, int, or str — float is not allowed "
                "for monetary values to avoid precision errors"
            )
        return v


class PartnerData(BaseModel):
    """Raw partner data as a nested object (not a JSON string).

    Represents the original partner transaction before normalization.
    """

    id: str
    trace: Optional[str] = None
    status: str
    amount: Decimal
    currency: str
    transDate: Optional[datetime] = None
    extra: dict[str, Any] = {}

    @field_validator("amount", mode="before")
    @classmethod
    def reject_float(cls, v: Any) -> Any:
        if isinstance(v, float):
            raise ValueError(
                "amount must be Decimal, int, or str — float is not allowed"
            )
        return v


class ValidationError(BaseModel):
    """Validation error for a specific field or row."""

    field: str
    reason: str
    row: Optional[int] = None
    trace: Optional[str] = None


class ProcessingStats(BaseModel):
    """Statistics for a file processing run."""

    total_rows: int
    success_rows: int
    failed_rows: int
    duplicate_rows: int = 0


class BatchInsertResult(BaseModel):
    """Detailed result for a batch persistence attempt."""

    inserted: int
    duplicates: int = 0
    failed: int = 0

    @property
    def attempted(self) -> int:
        return self.inserted + self.duplicates + self.failed
