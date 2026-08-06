"""Domain models and contracts for ingestion."""

from .checkpoints import (
    CheckpointRepository,
    CheckpointStatus,
    IngestionCheckpoint,
    IngestionMode,
)
from .source_units import IngestionOutcome, SourceUnitMetadata

from .ports import (
    IngestionFileRepository,
    MappingConfigRepositoryPort,
    PartnerTransactionWriter,
)

__all__ = [
    "IngestionFileRepository",
    "MappingConfigRepositoryPort",
    "PartnerTransactionWriter",
    "IngestionOutcome",
    "SourceUnitMetadata",
    "CheckpointRepository",
    "CheckpointStatus",
    "IngestionCheckpoint",
    "IngestionMode",
]
