"""Compatibility facade for the domain retry policy."""

from src.domain.ingestion.retry_policy import RetryDisposition, RetryPolicy

__all__ = ["RetryDisposition", "RetryPolicy"]
