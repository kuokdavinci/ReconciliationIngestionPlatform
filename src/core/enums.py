"""Core enums for processing status, transaction status, and file types."""

from enum import StrEnum


class ProcessingStatus(StrEnum):
    """Status of a file processing job."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TransactionStatus(StrEnum):
    """Status of an individual transaction."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PENDING = "PENDING"
    REVERSED = "REVERSED"


class FileType(StrEnum):
    """Type of ingestion file."""

    SETTLEMENT = "SETTLEMENT"
    RECONCILIATION = "RECONCILIATION"


class ReconciliationStatus(StrEnum):
    """Status of reconciliation result."""

    MATCHED = "MATCHED"
    MATCHED_FAILED = "MATCHED_FAILED"
    MATCHED_REVERSED = "MATCHED_REVERSED"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    STATUS_MISMATCH = "STATUS_MISMATCH"
    MULTIPLE_MISMATCH = "MULTIPLE_MISMATCH"
    MISSING_INTERNAL = "MISSING_INTERNAL"
    MISSING_PARTNER = "MISSING_PARTNER"
    AMBIGUOUS_KEY = "AMBIGUOUS_KEY"
    UNMAPPED_SKIPPED = "UNMAPPED_SKIPPED"


class ReconciliationScopeType(StrEnum):
    """Scope classification for a reconciliation file/run."""

    UNCONFIRMED = "UNCONFIRMED"
    FULL_SNAPSHOT = "FULL_SNAPSHOT"
    INCREMENTAL_APPEND = "INCREMENTAL_APPEND"
    REPLACEMENT = "REPLACEMENT"
