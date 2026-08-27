"""Read one bounded raw source row without loading the whole source into memory."""

import json
from pathlib import Path
from typing import Any

from src.config.signature import read_raw_rows


def _sanitize_json_value(value: Any) -> Any:
    """Match JSONStreamReader's float handling while preserving object keys."""
    if isinstance(value, float):
        return str(value)
    if isinstance(value, dict):
        return {key: _sanitize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return tuple(_sanitize_json_value(item) for item in value)
    return value


def read_authoritative_row(file_path: str | Path, row_number: int) -> Any | None:
    """Return the one-based physical source row requested by quarantine replay.

    CSV/XLSX sources are returned as tuples, matching the stream readers. JSON
    object records retain their keys so mappings that use ``sourceField`` keep
    working after a replay.
    """
    if row_number < 1:
        raise ValueError("row_number must be positive")

    path = Path(file_path)
    if path.suffix.lower() == ".json":
        with path.open(encoding="utf-8") as source:
            payload = json.load(source)
        records = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(records, list) or row_number > len(records):
            return None
        record = _sanitize_json_value(records[row_number - 1])
        if isinstance(record, tuple):
            return record
        if isinstance(record, dict):
            return record
        return (record,)

    rows = read_raw_rows(path, max_rows=row_number)
    if row_number > len(rows):
        return None
    return tuple(rows[row_number - 1])


__all__ = ["read_authoritative_row"]
