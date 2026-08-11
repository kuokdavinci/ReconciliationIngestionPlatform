"""Domain models and contracts for ingestion."""

from .checkpoints import (
    CheckpointRepository,
    CheckpointStatus,
    IngestionCheckpoint,
    IngestionMode,
    SourceUnitStatus,
    SourceUnitSummary,
)
from .source_units import IngestionOutcome, SourceUnitMetadata
from .raw_pages import RawIngestionPage, RawPageStatus

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
    "RawIngestionPage",
    "RawPageStatus",
    "CheckpointRepository",
    "CheckpointStatus",
    "IngestionCheckpoint",
    "IngestionMode",
    "SourceUnitStatus",
    "SourceUnitSummary",
]
