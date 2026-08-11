"""Canonical reconciliation-key normalization."""

from collections.abc import Iterable


def normalize_reconciliation_key(*candidates: object) -> str | None:
    """Return the first non-empty, trimmed reconciliation-key candidate."""

    for candidate in candidates:
        if candidate is None:
            continue
        value = str(candidate).strip()
        if value:
            return value
    return None


def normalize_reconciliation_keys(values: Iterable[object]) -> set[str]:
    """Normalize a collection of keys while discarding null/blank values."""

    return {
        value
        for value in (normalize_reconciliation_key(item) for item in values)
        if value is not None
    }
