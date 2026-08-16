"""Pure helpers for reviewer-facing reconciliation scope evidence."""

from collections.abc import Iterable
from typing import Any


def _scope_probabilities(
    *,
    internal_count: int,
    received_count: int,
) -> tuple[dict[str, float], str, str]:
    if received_count <= 0:
        return (
            {"FULL_SNAPSHOT": 0.34, "INCREMENTAL_APPEND": 0.33, "REPLACEMENT": 0.33},
            "FULL_SNAPSHOT",
            "No reliable row-count signal was available, so the suggestion stays conservative.",
        )
    if internal_count <= 0:
        return (
            {"FULL_SNAPSHOT": 0.9, "INCREMENTAL_APPEND": 0.07, "REPLACEMENT": 0.03},
            "FULL_SNAPSHOT",
            "There are no same-day internal rows yet, so the incoming file is most likely the day snapshot.",
        )

    larger = max(internal_count, received_count)
    diff = abs(internal_count - received_count)
    diff_ratio = diff / larger if larger > 0 else 0.0
    tolerance = max(10, int(larger * 0.05))
    if diff <= tolerance or diff_ratio <= 0.05:
        return (
            {"FULL_SNAPSHOT": 0.82, "INCREMENTAL_APPEND": 0.14, "REPLACEMENT": 0.04},
            "FULL_SNAPSHOT",
            "Received and internal counts are close enough that a few missing or mismatched rows still fit a full snapshot scenario.",
        )
    if received_count < internal_count * 0.8:
        return (
            {"FULL_SNAPSHOT": 0.18, "INCREMENTAL_APPEND": 0.72, "REPLACEMENT": 0.1},
            "INCREMENTAL_APPEND",
            "The incoming file is materially smaller than the same-day internal population, which is more consistent with a partial append batch.",
        )
    return (
        {"FULL_SNAPSHOT": 0.62, "INCREMENTAL_APPEND": 0.28, "REPLACEMENT": 0.1},
        "FULL_SNAPSHOT",
        "The file does not show strong incremental or replacement signals, so the default recommendation leans toward a full-day snapshot.",
    )


def _normalize_scope_probabilities(raw: object) -> dict[str, float]:
    default = {"FULL_SNAPSHOT": 0.34, "INCREMENTAL_APPEND": 0.33, "REPLACEMENT": 0.33}
    if not isinstance(raw, dict):
        return default
    normalized = {
        scope: float(raw.get(scope, 0.0) or 0.0)
        for scope in ("FULL_SNAPSHOT", "INCREMENTAL_APPEND", "REPLACEMENT")
    }
    total = sum(max(value, 0.0) for value in normalized.values())
    if total <= 0:
        return default
    return {scope: max(value, 0.0) / total for scope, value in normalized.items()}


def _apply_scope_guardrails(
    *,
    ai_scope: str,
    ai_probabilities: dict[str, float],
    ai_reasoning: str,
    heuristic_scope: str,
    heuristic_probabilities: dict[str, float],
    heuristic_reasoning: str,
    internal_count: int,
    received_count: int,
) -> tuple[dict[str, float], str, str, str]:
    larger = max(internal_count, received_count, 1)
    diff = abs(internal_count - received_count)
    diff_ratio = diff / larger
    if ai_scope == "INCREMENTAL_APPEND" and (
        (larger >= 10_000 and diff_ratio <= 0.05)
        or (larger >= 100_000 and diff <= max(10, int(larger * 0.01)))
    ):
        return (
            heuristic_probabilities,
            heuristic_scope,
            (
                f"{ai_reasoning} Guardrail override applied: count gap is too small relative to file size "
                "to treat this as a confident append-only batch."
            ).strip(),
            "guardrail_override_small_gap",
        )
    return ai_probabilities, ai_scope, ai_reasoning, "llm"


def _column_index(column: object) -> int | None:
    """Convert a 1-based mapping column (number or Excel letters) to an index."""
    if isinstance(column, int):
        return column - 1 if column > 0 else None
    if not isinstance(column, str):
        return None
    value = column.strip().upper()
    if value.isdigit():
        number = int(value)
        return number - 1 if number > 0 else None
    if not value.isalpha():
        return None
    index = 0
    for character in value:
        index = index * 26 + ord(character) - ord("A") + 1
    return index - 1


def _scope_mapping_columns(
    config: object,
    structure_signature: dict | None = None,
) -> dict[str, object] | None:
    """Find the canonical fields needed to derive a reconciliation key."""
    mappings = getattr(config, "field_mappings", None) or []
    columns: dict[str, object] = {}
    for mapping in mappings:
        path = str(getattr(mapping, "path", "")).strip().lower()
        field_name = path.rsplit(".", 1)[-1]
        if field_name not in {"id", "trace", "vsptransid"}:
            continue
        column = getattr(mapping, "column", None)
        if column is not None:
            columns[field_name] = column
    if columns:
        return columns

    headers = (structure_signature or {}).get("headers") or []
    preferred_tokens = (
        "mstransid",
        "transactionid",
        "transid",
        "trace",
        "partnerid",
        "invoice",
        "reference",
    )
    for index, header in enumerate(headers):
        normalized = "".join(character for character in str(header).lower() if character.isalnum())
        if any(token in normalized for token in preferred_tokens):
            return {"trace": index + 1}
    return None


def _extract_scope_keys(
    rows: Iterable[Any],
    config: object,
    structure_signature: dict | None = None,
) -> tuple[int, set[str]]:
    """Extract unique incoming reconciliation keys without normalizing the row."""
    columns = _scope_mapping_columns(config, structure_signature)
    received_count = 0
    keys: set[str] = set()
    for row in rows:
        received_count += 1
        if columns is None:
            continue
        values: dict[str, str] = {}
        for name, column in columns.items():
            if isinstance(row, dict):
                value = row.get(column)
                if value is None and isinstance(column, int):
                    column_number = column
                    letters = ""
                    while column_number > 0:
                        column_number, remainder = divmod(column_number - 1, 26)
                        letters = chr(ord("A") + remainder) + letters
                    value = row.get(str(column)) or row.get(letters)
                if value is None and isinstance(column, str) and column.isdigit():
                    value = row.get(int(column))
            else:
                index = _column_index(column)
                value = row[index] if index is not None and index < len(row) else None
            if value is not None and str(value).strip():
                values[name] = str(value).strip()
        key = values.get("trace") or values.get("vsptransid") or values.get("id")
        if key:
            keys.add(key)
    return received_count, keys
