"""Source-unit normalization and checkpoint projection for stream runs."""

from collections.abc import Sequence
from typing import Any

from src.domain.ingestion.source_units import SourceUnitMetadata


def checkpoint_result(checkpoint: Any) -> dict[str, Any]:
    status = getattr(checkpoint.status, "value", checkpoint.status)
    return {
        "status": status,
        "currentUnitKey": checkpoint.current_unit_key,
        "lastCompletedUnitKey": checkpoint.last_completed_unit_key,
        "cursorBefore": checkpoint.cursor_before,
        "cursorAfter": checkpoint.cursor_after,
    }


def source_units(
    units: Sequence[SourceUnitMetadata | dict[str, Any]],
) -> list[SourceUnitMetadata]:
    return [SourceUnitMetadata.from_payload(unit) for unit in units]


def unit_high_water_mark(unit: SourceUnitMetadata) -> dict[str, Any]:
    return {
        "sourceUnitKey": unit.source_unit_key,
        "page": unit.page,
        "cursorAfter": unit.cursor_after,
        "contentHash": unit.content_hash,
        "hasMore": unit.has_more,
    }


__all__ = ["checkpoint_result", "source_units", "unit_high_water_mark"]
