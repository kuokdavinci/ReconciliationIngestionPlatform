"""Public exports for the ingestion bounded context.

Exports are resolved lazily so importing a leaf domain model does not trigger
the ports package and create a circular dependency.
"""

from importlib import import_module
from typing import Any


_EXPORTS = {
    "CheckpointRepository": ("checkpoints", "CheckpointRepository"),
    "CheckpointStatus": ("checkpoints", "CheckpointStatus"),
    "IngestionCheckpoint": ("checkpoints", "IngestionCheckpoint"),
    "IngestionMode": ("checkpoints", "IngestionMode"),
    "SourceUnitStatus": ("checkpoints", "SourceUnitStatus"),
    "SourceUnitSummary": ("checkpoints", "SourceUnitSummary"),
    "IngestionOutcome": ("source_units", "IngestionOutcome"),
    "SourceUnitMetadata": ("source_units", "SourceUnitMetadata"),
    "RawIngestionPage": ("raw_pages", "RawIngestionPage"),
    "RawPageStatus": ("raw_pages", "RawPageStatus"),
    "IngestionFileRepository": ("ports", "IngestionFileRepository"),
    "MappingConfigRepositoryPort": ("ports", "MappingConfigRepositoryPort"),
    "PartnerTransactionWriter": ("ports", "PartnerTransactionWriter"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = _EXPORTS[name]
    value = getattr(import_module(f"{__name__}.{module_name}"), attribute)
    globals()[name] = value
    return value
