"""Scope classification helpers for reconciliation files."""

from __future__ import annotations

from datetime import datetime
from collections.abc import Collection
from typing import Any

from src.core.enums import ReconciliationScopeType
from src.infrastructure.postgres.internal_transaction_repository import InternalTransactionRepository
from src.core.utils import business_day_bounds


def classify_key_scope(
    *,
    incoming_keys: Collection[str],
    historical_keys: Collection[str],
    prior_file_count: int = 0,
) -> dict[str, Any]:
    """Classify scope from business-key evidence, never from a filename.

    ``INCREMENTAL_APPEND`` is batch-only: a file with no overlap against a
    previously ingested same-day batch is an append even when every row is new.
    A file that covers the historical key set and adds rows supersedes the
    previous delivery and is therefore a ``REPLACEMENT`` candidate.
    """

    incoming = {str(key).strip() for key in incoming_keys if str(key).strip()}
    historical = {str(key).strip() for key in historical_keys if str(key).strip()}
    overlap = incoming & historical
    new_keys = incoming - historical
    incoming_count = len(incoming)
    historical_count = len(historical)
    overlap_count = len(overlap)
    new_count = len(new_keys)
    overlap_ratio = overlap_count / incoming_count if incoming_count else 0.0
    historical_coverage = overlap_count / historical_count if historical_count else 0.0
    new_ratio = new_count / incoming_count if incoming_count else 0.0

    signals = {
        "incomingUniqueBusinessKeyCount": incoming_count,
        "historicalUniqueBusinessKeyCount": historical_count,
        "overlapBusinessKeyCount": overlap_count,
        "newBusinessKeyCount": new_count,
        "overlapRatio": overlap_ratio,
        "historicalCoverage": historical_coverage,
        "newRatio": new_ratio,
        "priorFileCount": prior_file_count,
    }

    if incoming_count == 0:
        return {
            "scopeType": ReconciliationScopeType.UNCONFIRMED.value,
            "scopeConfidence": 0.2,
            "scopeReason": ["No business keys were available for scope classification."],
            "scopeSignals": signals,
        }

    if historical_count == 0:
        if prior_file_count == 0:
            return {
                "scopeType": ReconciliationScopeType.FULL_SNAPSHOT.value,
                "scopeConfidence": 0.92,
                "scopeReason": ["No prior same-day partner keys exist; the first delivery is treated as a full snapshot."],
                "scopeSignals": signals,
            }
        return {
            "scopeType": ReconciliationScopeType.UNCONFIRMED.value,
            "scopeConfidence": 0.55,
            "scopeReason": ["Prior files exist, but historical business keys are unavailable for comparison."],
            "scopeSignals": signals,
        }

    if overlap_count == 0:
        return {
            "scopeType": ReconciliationScopeType.INCREMENTAL_APPEND.value,
            "scopeConfidence": 0.98,
            "scopeReason": ["The file contains only new business keys and no key overlaps the prior same-day deliveries."],
            "scopeSignals": signals,
        }

    if historical_coverage == 1.0 and new_count > 0:
        return {
            "scopeType": ReconciliationScopeType.REPLACEMENT.value,
            "scopeConfidence": 0.96,
            "scopeReason": ["The file covers the prior same-day key set and adds new keys, so it supersedes the previous delivery."],
            "scopeSignals": signals,
        }

    if overlap_ratio >= 0.8:
        return {
            "scopeType": ReconciliationScopeType.REPLACEMENT.value,
            "scopeConfidence": 0.86,
            "scopeReason": ["Most incoming keys overlap prior deliveries, so the file is treated as a replacement candidate."],
            "scopeSignals": signals,
        }

    if new_count > 0 and (new_ratio >= 0.5 or overlap_ratio < 0.5):
        return {
            "scopeType": ReconciliationScopeType.INCREMENTAL_APPEND.value,
            "scopeConfidence": 0.9,
            "scopeReason": ["The incoming batch is predominantly new and does not replace the prior same-day key set."],
            "scopeSignals": signals,
        }

    return {
        "scopeType": ReconciliationScopeType.UNCONFIRMED.value,
        "scopeConfidence": 0.55,
        "scopeReason": ["Key overlap is ambiguous; reviewer selection is required."],
        "scopeSignals": signals,
    }


async def classify_scope(
    db: Any,
    *,
    partner: str,
    reconciliation_date: datetime | None,
    partner_default: ReconciliationScopeType = ReconciliationScopeType.UNCONFIRMED,
) -> dict[str, Any]:
    """Infer reconciliation scope and provide reviewer-facing reasoning."""
    reasons: list[str] = []
    signals: dict[str, Any] = {"defaultPartnerScope": partner_default.value}

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
        start_of_day, end_of_day = business_day_bounds(reconciliation_date)
        internal_db_record_count = await InternalTransactionRepository(
            db
        ).count_by_partner_and_date_range(
            partner,
            start_of_day,
            end_of_day,
        )
    signals["internalDbRecordCount"] = internal_db_record_count

    if same_day_file_count == 0:
        scope = ReconciliationScopeType.FULL_SNAPSHOT
        confidence = 0.82
        reasons.append("No prior same-day partner file exists, so this is treated as the first full snapshot.")
    elif internal_db_record_count == 0:
        scope = ReconciliationScopeType.UNCONFIRMED
        confidence = 0.45
        reasons.append("Prior files exist but no same-day internal rows are available for comparison.")
    else:
        reasons.append(
            f"{same_day_file_count} file(s) already exist for {partner} on this reconciliation date."
        )
        scope = partner_default
        confidence = 0.55 if scope == ReconciliationScopeType.UNCONFIRMED else 0.6
        reasons.append("Key evidence is required before choosing append, replacement, or snapshot.")

    if scope == ReconciliationScopeType.UNCONFIRMED:
        reasons.append("Unconfirmed scope is handled conservatively as file-scoped reconciliation until reviewed.")

    return {
        "scopeType": scope.value,
        "scopeConfidence": confidence,
        "scopeReason": reasons,
        "scopeSignals": signals,
    }
