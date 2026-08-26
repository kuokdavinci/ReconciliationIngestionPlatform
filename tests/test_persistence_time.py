from datetime import datetime, timedelta, timezone

from src.infrastructure.persistence.time import as_utc_naive


def test_aware_timestamp_is_persisted_as_utc_naive():
    source = datetime(2025, 1, 1, 15, tzinfo=timezone(timedelta(hours=7)))

    result = as_utc_naive(source)

    assert result == datetime(2025, 1, 1, 8)
    assert result.tzinfo is None


def test_naive_legacy_timestamp_is_not_reinterpreted():
    source = datetime(2025, 1, 1, 8)

    assert as_utc_naive(source) is source


def test_none_timestamp_remains_none():
    assert as_utc_naive(None) is None
