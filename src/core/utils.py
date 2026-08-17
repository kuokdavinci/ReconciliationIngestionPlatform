"""Core utility functions for the reconciliation ingestion platform.

Combines date templates, business day boundaries, file identity hashing,
and runtime error formatting.
"""

from datetime import date, datetime, time, timezone
import hashlib
import re
from zoneinfo import ZoneInfo

from src.config.settings import settings


# --- Date Templates ---
def interpolate_date(template: str, date: datetime) -> str:
    """Replace ``{date:<format>}`` placeholders with formatted date values."""

    def replace(match: re.Match[str]) -> str:
        return date.strftime(match.group(1) or "%Y%m%d")

    return re.sub(r"\{date:(.*?)\}", replace, template)


# --- Business Day ---
def business_date(value: datetime) -> date:
    """Resolve a timestamp to the configured local business date."""

    utc_value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return utc_value.astimezone(ZoneInfo(settings.business_timezone)).date()


def business_day_bounds(value: datetime) -> tuple[datetime, datetime]:
    """Return local timezone-aware bounds for one business date."""

    business_timezone = ZoneInfo(settings.business_timezone)
    resolved_date = business_date(value)
    return (
        datetime.combine(resolved_date, time.min, tzinfo=business_timezone),
        datetime.combine(resolved_date, time.max, tzinfo=business_timezone),
    )


def utc_business_day_bounds(value: datetime) -> tuple[datetime, datetime]:
    """Return UTC-aware bounds for one business date."""

    start, end = business_day_bounds(value)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


# --- File Identity ---
def compute_file_hash(file_path: str) -> str:
    """Return a stable SHA-256 fingerprint for a local source file."""

    digest = hashlib.sha256()
    with open(file_path, "rb") as source_file:
        for chunk in iter(lambda: source_file.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- Error Formatting ---
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


__all__ = [
    "interpolate_date",
    "business_date",
    "business_day_bounds",
    "utc_business_day_bounds",
    "compute_file_hash",
    "summarize_runtime_error",
]
