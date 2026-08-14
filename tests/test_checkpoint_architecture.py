"""Architecture checks for ingestion checkpoint contracts and adapter."""

from src.domain.ingestion.checkpoints import (
    CheckpointRepository,
    CheckpointStatus,
    IngestionCheckpoint,
    IngestionMode,
)
from src.infrastructure.ingestion.checkpoint_repository import IngestionCheckpointRepository
def test_checkpoint_domain_and_adapter_have_separate_ownership() -> None:
    assert CheckpointRepository.__module__ == "src.domain.ingestion.checkpoints"
    assert CheckpointStatus.__module__ == "src.domain.ingestion.checkpoints"
    assert IngestionCheckpoint.__module__ == "src.domain.ingestion.checkpoints"
    assert IngestionCheckpointRepository.__module__ == (
        "src.infrastructure.ingestion.checkpoint_repository"
    )
    assert IngestionMode.__module__ == "src.domain.ingestion.checkpoints"
