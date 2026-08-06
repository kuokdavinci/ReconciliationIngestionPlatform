"""Compatibility facade for ingestion checkpoint contracts and adapter."""

from src.domain.ingestion.checkpoints import CheckpointRepository, CheckpointStatus, IngestionCheckpoint, IngestionMode
from src.infrastructure.ingestion.checkpoint_repository import IngestionCheckpointRepository

__all__ = ["CheckpointRepository", "CheckpointStatus", "IngestionCheckpoint", "IngestionCheckpointRepository", "IngestionMode"]
