"""Pure mapping-workflow helpers for serialization and source references."""

import asyncio
from pathlib import Path
from typing import Any

from src.domain.mapping.models import MappingConfig


def column_index(column: object) -> int | None:
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


def apply_source_reference_strategy(
    mappings: list[dict],
    *,
    headers: list[str],
    source_file_name: str | None,
) -> list[dict]:
    """Convert column references to object keys for JSON-like sources."""
    if Path(source_file_name or "").suffix.lower() not in {
        ".json",
        ".jsonl",
        ".ndjson",
    }:
        return [dict(mapping) for mapping in mappings]

    normalized: list[dict] = []
    for mapping in mappings:
        item = dict(mapping)
        index = column_index(item.get("column"))
        if index is not None and index < len(headers):
            source_field = str(headers[index]).strip()
            if source_field:
                item.pop("column", None)
                item["sourceField"] = source_field
        normalized.append(item)
    return normalized


def serialize_mapping(config: MappingConfig) -> dict[str, Any]:
    data = config.model_dump(by_alias=True)
    data["_id"] = str(data["_id"])
    data["draftMappingId"] = data["_id"]
    data["draftMappingVersion"] = data.get("configVersion") or data["_id"]
    if data.get("fileType") is not None:
        data["fileType"] = str(data["fileType"])
    return data


def serialize_packet(packet) -> dict[str, Any]:
    data = packet.model_dump(by_alias=True)
    data["_id"] = str(data["_id"])
    data["reviewItemId"] = data["_id"]
    return data


def has_passing_runtime_gate(packet) -> bool:
    return any(
        gate.get("gateKey") == "runtime_validation"
        and str(gate.get("status", "")).lower() == "pass"
        for gate in packet.validation_gates or []
    )


def schedule_in_event_loop(awaitable) -> None:
    asyncio.create_task(awaitable)
