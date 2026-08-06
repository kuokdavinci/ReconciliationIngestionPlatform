"""Bounded retry policy shared by fetch and source-unit orchestration."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class RetryDisposition(StrEnum):
    """Whether an error may be retried automatically."""

    RETRYABLE = "RETRYABLE"
    TERMINAL = "TERMINAL"


@dataclass(frozen=True)
class RetryPolicy:
    """Classify source-unit errors and calculate bounded exponential backoff."""

    max_attempts: int = 3
    initial_backoff_seconds: int = 60
    max_backoff_seconds: int = 3600

    retryable_error_codes: frozenset[str] = frozenset(
        {
            "fetch_timeout",
            "fetch_network_error",
            "fetch_http_429",
            "fetch_http_5xx",
            "source_persist_error",
            "checkpoint_advance_error",
            "checkpoint_stale",
        }
    )

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.initial_backoff_seconds < 0:
            raise ValueError("initial_backoff_seconds must be non-negative")
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError(
                "max_backoff_seconds must be at least initial_backoff_seconds"
            )

    def classify(self, error_code: str) -> RetryDisposition:
        """Fail closed: only explicitly transient errors are auto-retryable."""
        if error_code in self.retryable_error_codes:
            return RetryDisposition.RETRYABLE
        return RetryDisposition.TERMINAL

    def can_retry(self, error_code: str, attempt_count: int) -> bool:
        """Return whether another automatic attempt is allowed."""
        return (
            self.classify(error_code) == RetryDisposition.RETRYABLE
            and 0 <= attempt_count < self.max_attempts
        )

    def next_retry_at(
        self,
        error_code: str,
        attempt_count: int,
        now: datetime | None = None,
    ) -> datetime | None:
        """Calculate the next retry time, or ``None`` for terminal/exhausted errors."""
        if not self.can_retry(error_code, attempt_count):
            return None
        current_time = now or datetime.now(UTC)
        exponent = max(attempt_count - 1, 0)
        delay = min(
            self.initial_backoff_seconds * (2**exponent),
            self.max_backoff_seconds,
        )
        return current_time + timedelta(seconds=delay)
