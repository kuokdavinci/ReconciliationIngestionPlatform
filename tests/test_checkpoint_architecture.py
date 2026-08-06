"""Architecture checks for ingestion checkpoint contracts and adapter."""

from src.domain.ingestion.checkpoints import (
    CheckpointRepository,
    CheckpointStatus,
    IngestionCheckpoint,
    IngestionMode,
)
from src.infrastructure.ingestion.checkpoint_repository import IngestionCheckpointRepository
from src.models.ingestion_checkpoint import (
    CheckpointRepository as LegacyCheckpointRepository,
    CheckpointStatus as LegacyCheckpointStatus,
    IngestionCheckpoint as LegacyIngestionCheckpoint,
    IngestionCheckpointRepository as LegacyIngestionCheckpointRepository,
    IngestionMode as LegacyIngestionMode,
)


def test_legacy_checkpoint_module_is_a_compatibility_facade() -> None:
    """Legacy imports must resolve to domain and infrastructure implementations."""

    assert LegacyCheckpointRepository is CheckpointRepository
    assert LegacyCheckpointStatus is CheckpointStatus
    assert LegacyIngestionCheckpoint is IngestionCheckpoint
    assert LegacyIngestionCheckpointRepository is IngestionCheckpointRepository
    assert LegacyIngestionMode is IngestionMode
