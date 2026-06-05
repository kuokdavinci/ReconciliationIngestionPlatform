"""Scope classification helpers for reconciliation files."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.core.enums import ReconciliationScopeType


def _filename_hints(file_name: str) -> tuple[list[str], ReconciliationScopeType | None]:
    lowered = file_name.lower()
    replacement_tokens = ["replace", "replacement", "rerun", "retry", "resend", "correct", "correction"]
    incremental_tokens = ["part", "batch", "delta", "append", "supplement", "wave"]
    snapshot_tokens = ["full", "final", "daily", "settlement"]

    matched: list[str] = []
    if any(token in lowered for token in replacement_tokens):
        matched.extend([token for token in replacement_tokens if token in lowered])
        return matched, ReconciliationScopeType.REPLACEMENT
    if any(token in lowered for token in incremental_tokens):
        matched.extend([token for token in incremental_tokens if token in lowered])
        return matched, ReconciliationScopeType.INCREMENTAL_APPEND
    if any(token in lowered for token in snapshot_tokens):
        matched.extend([token for token in snapshot_tokens if token in lowered])
        return matched, ReconciliationScopeType.FULL_SNAPSHOT
    return matched, None


async def classify_scope(
    db: Any,
    *,
    partner: str,
    file_name: str,
    reconciliation_date: datetime | None,
    partner_default: ReconciliationScopeType = ReconciliationScopeType.UNCONFIRMED,
) -> dict[str, Any]:
    """Infer reconciliation scope and provide reviewer-facing reasoning."""
    reasons: list[str] = []
    signals: dict[str, Any] = {"defaultPartnerScope": partner_default.value}

    hints, hinted_scope = _filename_hints(file_name)
    if hints:
        signals["filenameHints"] = hints
        reasons.append(f"Filename contains scope hints: {', '.join(hints)}.")

    same_day_file_count = 0
    if reconciliation_date is not None:
        same_day_file_count = await db["reconciliation_file"].count_documents(
            {"partner": partner, "reconciliationDate": reconciliation_date}
        )
    signals["sameDayFileCount"] = same_day_file_count

    if same_day_file_count > 0:
        reasons.append(
            f"{same_day_file_count} file(s) already exist for {partner} on this reconciliation date."
        )
        if hinted_scope == ReconciliationScopeType.REPLACEMENT:
            scope = ReconciliationScopeType.REPLACEMENT
            confidence = 0.9
        else:
            scope = ReconciliationScopeType.INCREMENTAL_APPEND
            confidence = 0.8 if hinted_scope is None else 0.88
            reasons.append("Multiple files on the same date are treated as additive until explicitly replaced.")
    elif hinted_scope is not None:
        scope = hinted_scope
        confidence = 0.78
    else:
        scope = partner_default
        confidence = 0.55 if scope == ReconciliationScopeType.UNCONFIRMED else 0.7
        reasons.append("No reliable scope signal was found; falling back to the partner default.")

    if scope == ReconciliationScopeType.UNCONFIRMED:
        reasons.append("Unconfirmed scope is handled conservatively as file-scoped reconciliation until reviewed.")

    return {
        "scopeType": scope.value,
        "scopeConfidence": confidence,
        "scopeReason": reasons,
        "scopeSignals": signals,
    }
