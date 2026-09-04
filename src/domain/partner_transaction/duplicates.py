"""Domain contract for partner-transaction duplicate equivalence."""

from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.ingestion.quality import QualityRuleCode


def _normalized_decimal(value: Any) -> str:
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    if decimal_value == 0:
        return "0"
    return format(decimal_value.normalize(), "f")


def _normalized_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        return str(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _canonical_metadata(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _normalized_decimal(value)
    if isinstance(value, datetime):
        return _normalized_datetime(value)
    if isinstance(value, dict):
        return {
            str(key): _canonical_metadata(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_metadata(item) for item in value]
    return value


def fingerprint_payload(payload: dict[str, Any]) -> str:
    """Hash the business fields that define duplicate payload equivalence."""

    canonical = {
        "partner_id": str(payload.get("partner_id", payload.get("partnerId")) or ""),
        "partner_trace": payload.get("partner_trace", payload.get("partnerTrace")),
        "partner_status": payload.get("partner_status", payload.get("partnerStatus")),
        "amount": _normalized_decimal(payload.get("partner_amount", payload.get("amount", 0))),
        "currency": payload.get("partner_currency", payload.get("currency")),
        "transDate": _normalized_datetime(
            payload.get("partner_trans_date", payload.get("transDate"))
        ),
        "metadata": _canonical_metadata(
            payload.get("partner_metadata", payload.get("metadata")) or {}
        ),
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class DuplicateDetail(BaseModel):
    """Typed evidence for one key conflict in an incoming batch."""

    model_config = ConfigDict(extra="forbid")

    identify: str
    ingestion_key: str
    duplicate_type: QualityRuleCode
    incoming_index: int = Field(ge=0)
    incoming_fingerprint: str
    existing_fingerprint: str
    partner_id: str | None = None
    partner_trace: str | None = None
    row_context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_duplicate_rule(self) -> "DuplicateDetail":
        if self.duplicate_type not in {
            QualityRuleCode.EQUIVALENT_DUPLICATE,
            QualityRuleCode.CONFLICTING_DUPLICATE,
        }:
            raise ValueError("duplicate_type must be an equivalent or conflicting rule")
        return self


class BatchWriteResult(BaseModel):
    """Complete typed result for one conflict-safe batch write."""

    model_config = ConfigDict(extra="forbid")

    inserted: int = Field(ge=0)
    duplicates: int = Field(default=0, ge=0)
    equivalent_duplicates: int = Field(default=0, ge=0)
    conflicting_duplicates: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    duplicate_details: list[DuplicateDetail] = Field(default_factory=list)
    # Optional observability data; persistence callers may ignore it.
    timings_ms: dict[str, float] = Field(default_factory=dict)

    def __eq__(self, other: object) -> bool:
        """Keep legacy result comparisons independent of observability fields."""
        if not isinstance(other, BatchWriteResult):
            return NotImplemented
        return self.model_dump(exclude={"timings_ms"}) == other.model_dump(
            exclude={"timings_ms"}
        )

    @model_validator(mode="after")
    def validate_duplicate_accounting(self) -> "BatchWriteResult":
        classified = self.equivalent_duplicates + self.conflicting_duplicates
        if classified != self.duplicates or len(self.duplicate_details) != self.duplicates:
            raise ValueError("duplicate details and classified counts must equal duplicates")
        equivalent = sum(
            detail.duplicate_type is QualityRuleCode.EQUIVALENT_DUPLICATE
            for detail in self.duplicate_details
        )
        conflicting = sum(
            detail.duplicate_type is QualityRuleCode.CONFLICTING_DUPLICATE
            for detail in self.duplicate_details
        )
        if equivalent != self.equivalent_duplicates or conflicting != self.conflicting_duplicates:
            raise ValueError("duplicate details must match equivalent/conflicting counts")
        incoming_indexes = [detail.incoming_index for detail in self.duplicate_details]
        if len(set(incoming_indexes)) != len(incoming_indexes) or any(
            index >= self.attempted for index in incoming_indexes
        ):
            raise ValueError(
                "duplicate incoming indexes must be unique and within the attempted batch"
            )
        return self

    @property
    def attempted(self) -> int:
        return self.inserted + self.duplicates + self.failed


__all__ = [
    "BatchWriteResult",
    "DuplicateDetail",
    "fingerprint_payload",
]
