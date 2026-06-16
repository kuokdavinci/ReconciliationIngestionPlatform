"""Helpers to keep operational error messages concise in UI-facing status fields."""

from typing import Any


def summarize_runtime_error(exc: Exception) -> str:
    """Return a short UI-safe summary for long backend exceptions."""
    text = str(exc or "").strip()
    if not text:
        return "Unexpected runtime error."

    lowered = text.lower()
    if "duplicate key error" in lowered and "reconciliation_result" in lowered:
        record_id = _extract_duplicate_key_value(text)
        if record_id:
            return f"Reconciliation results already exist for record {record_id}. Clear or replace existing results before rerunning."
        return "Reconciliation results already exist for this partner/date. Clear or replace existing results before rerunning."

    if "batch op errors occurred" in lowered and "duplicate key" in lowered:
        return "Reconciliation insert failed because duplicate result rows already exist."

    if len(text) > 220:
        return text[:217].rstrip() + "..."
    return text


def _extract_duplicate_key_value(text: str) -> str | None:
    marker = "dup key: { _id: "
    if marker not in text:
        return None
    tail = text.split(marker, 1)[1]
    if " }" not in tail:
        return None
    raw_value = tail.split(" }", 1)[0].strip()
    return raw_value.strip('"').strip("'")
