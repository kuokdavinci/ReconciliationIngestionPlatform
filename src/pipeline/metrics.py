"""Metrics formatting for ingestion performance logs."""

from dataclasses import dataclass


@dataclass(frozen=True)
class IngestionPerformance:
    """Stage timings and counters emitted after one ingestion run."""

    total_ingest_ms: float
    read_file_ms: float
    parse_rows_ms: float
    normalize_ms: float
    validate_ms: float
    db_insert_ms: float
    post_insert_update_ms: float
    records_count: int
    batch_size: int
    db_write_operation_count: int
    error_count: int
    slowest_batch_ms: float

    def to_log_line(self) -> str:
        return (
            "PERF_INGEST: "
            f"total_ingest_ms={self.total_ingest_ms:.2f} "
            f"read_file_ms={self.read_file_ms:.2f} "
            f"parse_rows_ms={self.parse_rows_ms:.2f} "
            f"normalize_ms={self.normalize_ms:.2f} "
            f"validate_ms={self.validate_ms:.2f} "
            "deduplicate_ms=0.00 "
            f"db_insert_ms={self.db_insert_ms:.2f} "
            f"post_insert_update_ms={self.post_insert_update_ms:.2f} "
            f"records_count={self.records_count} "
            f"batch_size={self.batch_size} "
            f"db_write_operation_count={self.db_write_operation_count} "
            f"error_count={self.error_count} "
            f"slowest_batch_ms={self.slowest_batch_ms:.2f}"
        )
