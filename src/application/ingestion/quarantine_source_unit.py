"""Source-unit blocker policy for quarantine-driven resume decisions."""

from dataclasses import dataclass
from typing import Any

from src.domain.ingestion.quarantine import IngestionQuarantineRecord, QuarantineStatus
from src.domain.ingestion.quarantine import QuarantineQuery


@dataclass(frozen=True, slots=True)
class SourceUnitResolutionResult:
    """Bounded policy result consumed by a later resume operation."""

    source_unit_key: str
    blocker_count: int
    resolved_count: int
    ready_to_resume: bool
    reason: str


def _is_conflict(record: IngestionQuarantineRecord) -> bool:
    return any(
        isinstance(error, dict)
        and (
            error.get("errorCode") == "CONFLICTING_DUPLICATE"
            or error.get("error_code") == "CONFLICTING_DUPLICATE"
        )
        for error in record.errors
    )


async def _all_records(
    quarantine_repo: Any,
    source_unit_key: str,
    active: list[IngestionQuarantineRecord],
) -> list[IngestionQuarantineRecord]:
    finder = getattr(quarantine_repo, "find_many", None)
    if not callable(finder):
        return active
    result = await finder(QuarantineQuery(sourceUnitKey=source_unit_key, limit=200))
    records = result[0] if isinstance(result, tuple) else result
    return [
        record
        for record in records
        if getattr(record, "source_unit_key", None) == source_unit_key
    ]


async def resolve_quarantine_source_unit(
    source_unit_key: str,
    operator_id: str,
    reason: str,
    quarantine_repo: Any | None = None,
) -> SourceUnitResolutionResult:
    """Evaluate whether a source unit may resume without mutating it.

    ``operator_id`` and ``reason`` are accepted as the audit context for the
    caller that requested this evaluation. The actual append-only transition
    remains in the quarantine repository and checkpoint resume operation.
    """
    del operator_id, reason
    if quarantine_repo is None:
        return SourceUnitResolutionResult(
            source_unit_key=source_unit_key,
            blocker_count=0,
            resolved_count=0,
            ready_to_resume=True,
            reason="NO_UNRESOLVED_BLOCKERS",
        )

    active = await quarantine_repo.find_blockers(source_unit_key)
    active = [
        record
        for record in active
        if getattr(record, "source_unit_key", None) == source_unit_key
    ]
    blockers = [record for record in active if _is_conflict(record)]
    records = await _all_records(quarantine_repo, source_unit_key, active)
    resolved_count = sum(
        record.status in {QuarantineStatus.RESOLVED, QuarantineStatus.REJECTED}
        and _is_conflict(record)
        for record in records
    )
    ready = not blockers
    return SourceUnitResolutionResult(
        source_unit_key=source_unit_key,
        blocker_count=len(blockers),
        resolved_count=resolved_count,
        ready_to_resume=ready,
        reason=(
            "UNRESOLVED_CONFLICTING_DUPLICATE"
            if blockers
            else "READY_AFTER_CONFLICT_RESOLUTION"
            if resolved_count
            else "NO_UNRESOLVED_BLOCKERS"
        ),
    )


__all__ = [
    "SourceUnitResolutionResult",
    "resolve_quarantine_source_unit",
]
