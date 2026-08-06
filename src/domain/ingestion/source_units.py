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
    def from_payload(cls, payload: "SourceUnitMetadata | Mapping[str, Any]") -> "SourceUnitMetadata":
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

    @staticmethod
    def _accepted_duplicate(value: Any) -> bool:
        return value in {"FILE_DUPLICATE", "FETCH_UNIT_REPLAY"}

    @staticmethod
    def _first(payload: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
        for key in keys:
            if key in payload and payload[key] is not None:
                return payload[key]
        return default

    @classmethod
    def from_result(cls, result: Any) -> "IngestionOutcome":
        """Convert supported ingestion result shapes into one contract."""

        if isinstance(result, cls):
            return result
        if isinstance(result, bool):
            return cls(success=result)
        if isinstance(result, Mapping):
            accepted_duplicate = cls._accepted_duplicate(result.get("outcome"))
            waiting_for_review = (
                result.get("outcome") == "WAITING_REVIEW"
                or bool(result.get("waitingForReview"))
                or bool(result.get("waiting_for_review"))
            )
            retryable = result.get("retryable", True)
            return cls(
                success=bool(result.get("success", False) or accepted_duplicate),
                error=cls._first(result, "error", default=cls.error),
                error_code=cls._first(
                    result, "errorCode", "error_code", default=cls.error_code
                ),
                retryable=True if retryable is None else bool(retryable),
                next_retry_at=cls._first(result, "nextRetryAt", "next_retry_at"),
                error_metadata=cls._first(
                    result, "errorMetadata", "error_metadata", default={}
                ),
                waiting_for_review=waiting_for_review,
            )

        processing_status = getattr(
            getattr(result, "file_record", None), "processing_status", None
        )
        status = getattr(processing_status, "value", processing_status)
        accepted_duplicate = cls._accepted_duplicate(getattr(result, "outcome", None))
        waiting_for_review = getattr(result, "outcome", None) == "WAITING_REVIEW"
        return cls(
            success=status == "COMPLETED" or accepted_duplicate,
            error=getattr(result, "error", cls.error),
            error_code=getattr(result, "error_code", "source_persist_error"),
            waiting_for_review=waiting_for_review,
        )
