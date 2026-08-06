"""Observability vocabulary for ingestion stages."""

from enum import StrEnum


class IngestionStage(StrEnum):
    CLAIMING = "CLAIMING"
    CONFIGURING = "CONFIGURING"
    READING = "READING"
    PROCESSING = "PROCESSING"
    PERSISTING = "PERSISTING"
    QUARANTINING = "QUARANTINING"
    FINALIZING = "FINALIZING"
