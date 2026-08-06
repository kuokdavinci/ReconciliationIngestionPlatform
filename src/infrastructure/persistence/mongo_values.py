"""Mongo value deserialization shared by persistence adapters."""

from collections.abc import Mapping
from typing import Any


def convert_from_mongo_types(value: Any) -> Any:
    """Convert Mongo-specific scalar values without depending on a repository."""
    from bson.decimal128 import Decimal128

    if isinstance(value, Decimal128):
        return value.to_decimal()
    if isinstance(value, dict):
        return {key: convert_from_mongo_types(item) for key, item in value.items()}
    if isinstance(value, list):
        return [convert_from_mongo_types(item) for item in value]
    return value


def normalize_document_aliases(
    document: Mapping[str, Any], aliases: Mapping[str, str]
) -> dict[str, Any]:
    """Deserialize a document and translate its external keys to domain keys."""
    converted = convert_from_mongo_types(dict(document))
    return {aliases.get(key, key): value for key, value in converted.items()}
