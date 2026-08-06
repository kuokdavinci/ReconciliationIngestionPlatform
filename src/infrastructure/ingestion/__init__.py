"""Infrastructure adapters for the ingestion bounded context."""

from .checkpoint_repository import IngestionCheckpointRepository

__all__ = ["IngestionCheckpointRepository"]
