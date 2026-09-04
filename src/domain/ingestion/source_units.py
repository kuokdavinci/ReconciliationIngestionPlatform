"""Typed contracts shared by fetchers and source-unit orchestration."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field


class SourceUnitMetadata(BaseModel):
    """Canonical representation of one discovered source unit."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    source_unit_key: str | None = Field(default=None, alias="sourceUnitKey")
    source_identity: dict[str, Any] = Field(default_factory=dict, alias="sourceIdentity")
    local_path: str | None = Field(default=None, alias="localPath")
    file_size: int = Field(default=0, alias="fileSize")
    content_hash: str | None = Field(default=None, alias="contentHash")
    status: str | None = None
    page: int | None = None
    cursor_before: str | None = Field(default=None, alias="cursorBefore")
    cursor_after: str | None = Field(default=None, alias="cursorAfter")
    high_water_mark: dict[str, Any] | None = Field(default=None, alias="highWaterMark")
    status_code: int | None = Field(default=None, alias="statusCode")
    content_type: str | None = Field(default=None, alias="contentType")
    item_count: int | None = Field(default=None, alias="itemCount")
    has_more: bool | None = Field(default=None, alias="hasMore")
    error: str | None = None
    error_code: str | None = Field(default=None, alias="errorCode")
    fetch_metadata: dict[str, Any] = Field(default_factory=dict, alias="fetchMetadata")

    @classmethod
    def from_payload(
        cls, payload: "SourceUnitMetadata | Mapping[str, Any]"
    ) -> "SourceUnitMetadata":
        """Parse a legacy mapping once at a system boundary."""

        if isinstance(payload, cls):
            return payload
        return cls.model_validate(payload)

    @classmethod
    def _field_name(cls, key: str) -> str | None:
        if key in cls.model_fields:
            return key
        for name, field_info in cls.model_fields.items():
            if field_info.alias == key:
                return name
        return None

    def get(self, key: str, default: Any = None) -> Any:
        """Read a field using either the canonical or legacy key."""

        field_name = self._field_name(key)
        if field_name is not None:
            return getattr(self, field_name)
        return (self.__pydantic_extra__ or {}).get(key, default)

    def __getitem__(self, key: str) -> Any:
        value = self.get(key)
        if value is None and key not in self.model_dump(by_alias=True, exclude_none=False):
            raise KeyError(key)
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        field_name = self._field_name(key)
        if field_name is not None:
            setattr(self, field_name, value)
            return
        setattr(self, key, value)


@dataclass
class IngestionOutcome:
    """Normalized result consumed by the source-unit state machine."""

    success: bool
    error: str = "Source unit ingestion failed"
    error_code: str = "source_unit_failed"
    retryable: bool = True
    next_retry_at: datetime | None = None
    error_metadata: dict[str, Any] = field(default_factory=dict)
    waiting_for_review: bool = False
    quality_decision: str | None = None
    orchestration_action: str | None = None
    quality_counters: dict[str, int] = field(default_factory=dict)
    top_rule_codes: list[str] = field(default_factory=list)

    @staticmethod
    def _accepted_duplicate(value: Any) -> bool:
        return value in {"FILE_DUPLICATE", "FETCH_UNIT_REPLAY"}

    @staticmethod
    def _completed_status(value: Any) -> bool:
        return value in {"COMPLETED", "PARTIAL"}

    @staticmethod
    def _first(payload: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
        for key in keys:
            if key in payload and payload[key] is not None:
                return payload[key]
        return default

    @staticmethod
    def _quality_review_reason(
        top_rule_codes: list[str],
        orchestration_action: str | None,
    ) -> str:
        code = (
            "CONFLICTING_DUPLICATE"
            if orchestration_action == "HOLD_FOR_REVIEW"
            else top_rule_codes[0]
            if top_rule_codes
            else "UNSPECIFIED"
        )
        return f"quality_review:{code}"

    @classmethod
    def from_result(cls, result: Any) -> "IngestionOutcome":
        """Convert supported ingestion result shapes into one contract."""

        if isinstance(result, cls):
            return result
        if isinstance(result, bool):
            return cls(success=result)
        if isinstance(result, Mapping):
            accepted_duplicate = cls._accepted_duplicate(result.get("outcome"))
            partial = result.get("outcome") == "PARTIAL"
            orchestration_action = cls._first(
                result,
                "orchestrationAction",
                "orchestration_action",
            )
            quality_failed = orchestration_action == "FAIL"
            waiting_for_review = (
                result.get("outcome") == "WAITING_REVIEW"
                or bool(result.get("waitingForReview"))
                or bool(result.get("waiting_for_review"))
                or orchestration_action == "HOLD_FOR_REVIEW"
            )
            retryable = result.get("retryable", True)
            top_rule_codes = list(
                cls._first(result, "topRuleCodes", "top_rule_codes", default=[]) or []
            )
            error = cls._first(result, "error", default=None)
            if error is None:
                error = (
                    cls._quality_review_reason(
                        top_rule_codes,
                        orchestration_action,
                    )
                    if waiting_for_review
                    else cls.error
                )
            return cls(
                success=(
                    bool(result.get("success", False) or accepted_duplicate or partial)
                    and not quality_failed
                ),
                error=error,
                error_code=(
                    "quality_batch_fatal"
                    if quality_failed
                    else cls._first(
                        result,
                        "errorCode",
                        "error_code",
                        default=cls.error_code,
                    )
                ),
                retryable=True if retryable is None else bool(retryable),
                next_retry_at=cls._first(result, "nextRetryAt", "next_retry_at"),
                error_metadata=cls._first(result, "errorMetadata", "error_metadata", default={}),
                waiting_for_review=waiting_for_review,
                quality_decision=cls._first(result, "qualityDecision", "quality_decision"),
                orchestration_action=orchestration_action,
                quality_counters=cls._first(
                    result, "qualityCounters", "quality_counters", default={}
                ),
                top_rule_codes=top_rule_codes,
            )

        processing_status = getattr(getattr(result, "file_record", None), "processing_status", None)
        status = getattr(processing_status, "value", processing_status)
        accepted_duplicate = cls._accepted_duplicate(getattr(result, "outcome", None))
        orchestration_action = getattr(result, "orchestration_action", None)
        orchestration_action = getattr(orchestration_action, "value", orchestration_action)
        quality_decision = getattr(result, "quality_decision", None)
        quality_decision = getattr(quality_decision, "value", quality_decision)
        waiting_for_review = (
            getattr(result, "outcome", None) == "WAITING_REVIEW"
            or orchestration_action == "HOLD_FOR_REVIEW"
        )
        quality_failed = orchestration_action == "FAIL"
        top_rule_codes = list(
            getattr(
                getattr(result, "quality_summary", None),
                "top_rule_codes",
                [],
            )
            or []
        )
        error = getattr(result, "error", None)
        if error is None:
            error = (
                cls._quality_review_reason(
                    top_rule_codes,
                    orchestration_action,
                )
                if waiting_for_review
                else cls.error
            )
        return cls(
            success=(cls._completed_status(status) or accepted_duplicate) and not quality_failed,
            error=error,
            error_code=(
                "quality_batch_fatal"
                if quality_failed
                else getattr(result, "error_code", "source_persist_error")
            ),
            waiting_for_review=waiting_for_review,
            quality_decision=quality_decision,
            orchestration_action=orchestration_action,
            quality_counters=getattr(result, "quality_counters", {}) or {},
            top_rule_codes=top_rule_codes,
        )
