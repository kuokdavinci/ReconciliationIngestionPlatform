"""Resolve the safest available input for one quarantine reprocess action."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.domain.ingestion.quarantine import IngestionQuarantineRecord, QuarantineStatus


class QuarantineReprocessMode(StrEnum):
    """Explicit source choice made by the operator."""

    REPLAY_SOURCE_ROW = "REPLAY_SOURCE_ROW"
    CORRECTED_ROW = "CORRECTED_ROW"
    ACCEPT_EXISTING = "ACCEPT_EXISTING"
    REJECT = "REJECT"


class QuarantineReprocessRequest(BaseModel):
    """Validated command for resolving one quarantine record."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    record_id: str = Field(alias="recordId", min_length=1)
    operator_id: str = Field(alias="operatorId", min_length=1, max_length=128)
    action_id: str = Field(alias="actionId", min_length=1, max_length=128)
    expected_status: QuarantineStatus = Field(alias="expectedStatus")
    mode: QuarantineReprocessMode
    corrected_row: Any | None = Field(default=None, alias="correctedRow")
    mapping_version: str | None = Field(default=None, alias="mappingVersion")
    expected_existing_fingerprint: str | None = Field(
        default=None,
        alias="expectedExistingFingerprint",
    )
    reason: str | None = Field(default=None, max_length=500)


@dataclass(frozen=True, slots=True)
class ResolvedQuarantineInput:
    """Input selected for the shared normalizer/validator boundary."""

    row: Any
    origin: str
    mapping_version: str | None = None
    row_number: int | None = None


async def _read_row(repository: Any, key: str | None, row_number: int | None) -> Any:
    """Call the narrow row-reader contract without coupling to an adapter."""
    if repository is None or key is None or row_number is None:
        return None
    return await repository.read_row(key, row_number)


def _contains_sanitization_marker(value: Any) -> bool:
    """Detect markers introduced by ``sanitize_raw_row``."""
    if isinstance(value, dict):
        return any(_contains_sanitization_marker(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_sanitization_marker(item) for item in value)
    return isinstance(value, str) and (
        value == "[REDACTED]" or value.endswith("...")
    )


async def resolve_reprocess_input(
    record: IngestionQuarantineRecord,
    request: QuarantineReprocessRequest,
    source_file_repo: Any,
    raw_page_repo: Any,
) -> ResolvedQuarantineInput:
    """Select an authoritative or explicitly corrected row.

    The repositories expose a deliberately small ``read_row(key, row_number)``
    contract.  It never writes persistence state.
    """
    if request.mode is QuarantineReprocessMode.ACCEPT_EXISTING:
        return ResolvedQuarantineInput(
            row=None,
            origin=QuarantineReprocessMode.ACCEPT_EXISTING.value,
            mapping_version=request.mapping_version,
            row_number=record.row_number,
        )

    if request.mode is QuarantineReprocessMode.CORRECTED_ROW:
        if request.corrected_row is None:
            raise ValueError("correctedRow is required for corrected-row reprocess")
        return ResolvedQuarantineInput(
            row=request.corrected_row,
            origin=QuarantineReprocessMode.CORRECTED_ROW.value,
            mapping_version=request.mapping_version,
            row_number=record.row_number,
        )

    source_row = await _read_row(
        source_file_repo,
        record.source_file_id,
        record.row_number,
    )
    if source_row is not None:
        return ResolvedQuarantineInput(
            row=source_row,
            origin="AUTHORITATIVE_SOURCE_FILE",
            mapping_version=request.mapping_version or record.config_version,
            row_number=record.row_number,
        )

    staged_row = await _read_row(
        raw_page_repo,
        record.source_unit_key,
        record.row_number,
    )
    if staged_row is not None:
        return ResolvedQuarantineInput(
            row=staged_row,
            origin="STAGED_RAW_PAGE",
            mapping_version=request.mapping_version or record.config_version,
            row_number=record.row_number,
        )

    if record.raw_row is not None and not _contains_sanitization_marker(record.raw_row):
        return ResolvedQuarantineInput(
            row=record.raw_row,
            origin="QUARANTINE_ROW",
            mapping_version=request.mapping_version or record.config_version,
            row_number=record.row_number,
        )

    raise ValueError(
        "No authoritative source row is available for replay; provide correctedRow."
    )


__all__ = [
    "QuarantineReprocessMode",
    "QuarantineReprocessRequest",
    "ResolvedQuarantineInput",
    "resolve_reprocess_input",
]
