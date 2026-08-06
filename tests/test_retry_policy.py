"""TDD contracts for bounded retry and terminal error classification."""

from datetime import UTC, datetime, timedelta

from src.services.retry_policy import RetryDisposition, RetryPolicy


def test_transient_fetch_errors_are_retryable_with_exponential_backoff():
    policy = RetryPolicy(
        max_attempts=3,
        initial_backoff_seconds=10,
        max_backoff_seconds=30,
    )
    now = datetime(2024, 7, 7, tzinfo=UTC)

    assert policy.classify("fetch_timeout") == RetryDisposition.RETRYABLE
    assert policy.can_retry("fetch_timeout", attempt_count=1) is True
    assert policy.next_retry_at("fetch_timeout", 1, now) == now + timedelta(seconds=10)
    assert policy.next_retry_at("fetch_timeout", 2, now) == now + timedelta(seconds=20)


def test_terminal_errors_are_never_retryable():
    policy = RetryPolicy(max_attempts=3)

    assert policy.classify("pagination_parse_error") == RetryDisposition.TERMINAL
    assert policy.classify("invalid_credentials") == RetryDisposition.TERMINAL
    assert policy.can_retry("pagination_parse_error", attempt_count=1) is False
    assert policy.next_retry_at("pagination_parse_error", 1) is None


def test_retry_stops_when_max_attempts_is_exhausted():
    policy = RetryPolicy(max_attempts=3, initial_backoff_seconds=1)

    assert policy.can_retry("fetch_http_5xx", attempt_count=2) is True
    assert policy.can_retry("fetch_http_5xx", attempt_count=3) is False
    assert policy.next_retry_at("fetch_http_5xx", 3) is None


def test_unknown_errors_fail_closed_as_terminal():
    policy = RetryPolicy(max_attempts=3)

    assert policy.classify("new_unclassified_error") == RetryDisposition.TERMINAL
    assert policy.can_retry("new_unclassified_error", attempt_count=1) is False
