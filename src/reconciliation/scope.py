"""Scope classification helpers for reconciliation files."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.core.enums import ReconciliationScopeType
from src.infrastructure.postgres.internal_transaction_repository import InternalTransactionRepository


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
        file_coll = db["reconciliation_file"] if hasattr(db, "__getitem__") else getattr(db, "reconciliation_file", None)
        if file_coll is not None and hasattr(file_coll, "count_documents"):
            cnt_res = file_coll.count_documents(
                {"partner": partner, "reconciliationDate": reconciliation_date}
            )
            if hasattr(cnt_res, "__await__"):
                same_day_file_count = await cnt_res
            elif callable(cnt_res):
                same_day_file_count = cnt_res()
            else:
                same_day_file_count = cnt_res
            try:
                same_day_file_count = int(same_day_file_count)
            except (TypeError, ValueError):
                same_day_file_count = 0
    signals["sameDayFileCount"] = same_day_file_count

    internal_db_record_count = 0
    if reconciliation_date is not None:
        start_of_day = reconciliation_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = reconciliation_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        internal_db_record_count = await InternalTransactionRepository(
            db
        ).count_by_partner_and_date_range(
            partner,
            start_of_day,
            end_of_day,
        )
    signals["internalDbRecordCount"] = internal_db_record_count

    if same_day_file_count > 0:
        reasons.append(
            f"{same_day_file_count} file(s) already exist for {partner} on this reconciliation date."
        )
        if hinted_scope == ReconciliationScopeType.REPLACEMENT:
            scope = ReconciliationScopeType.REPLACEMENT
            confidence = 0.9
        elif hinted_scope == ReconciliationScopeType.INCREMENTAL_APPEND:
            scope = ReconciliationScopeType.INCREMENTAL_APPEND
            confidence = 0.88
            reasons.append("Filename explicitly suggests a partial or additive batch.")
        elif hinted_scope == ReconciliationScopeType.FULL_SNAPSHOT:
            scope = ReconciliationScopeType.FULL_SNAPSHOT
            confidence = 0.84
            reasons.append("Filename still points to a daily snapshot, so multiple same-day files are treated as a replacement snapshot candidate.")
        elif internal_db_record_count == 0:
            scope = ReconciliationScopeType.FULL_SNAPSHOT
            confidence = 0.82
            reasons.append("No same-day internal rows exist yet, so the file is still more likely a full snapshot than an append batch.")
        else:
            scope = ReconciliationScopeType.UNCONFIRMED
            confidence = 0.58
            reasons.append(
                "Another same-day file exists, but that alone is not enough to force append scope without filename or volume evidence."
            )
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
