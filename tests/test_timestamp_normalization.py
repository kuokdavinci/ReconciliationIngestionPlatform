from datetime import UTC, datetime, timedelta, timezone

import pytest

from src.normalizer.timestamps import (
    TimestampParseError,
    parse_transaction_timestamp,
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("2025-01-01T08:00:00Z", datetime(2025, 1, 1, 8, tzinfo=UTC)),
        ("2025-01-01T15:00:00+07:00", datetime(2025, 1, 1, 8, tzinfo=UTC)),
        ("2025-01-01T02:00:00-06:00", datetime(2025, 1, 1, 8, tzinfo=UTC)),
        (
            "2025-01-01T15:00:00.123456+07:00",
            datetime(2025, 1, 1, 8, 0, 0, 123456, tzinfo=UTC),
        ),
    ],
)
def test_offset_timestamp_is_normalized_to_utc(source, expected):
    assert parse_transaction_timestamp(source) == expected


def test_aware_datetime_is_normalized_to_utc():
    source = datetime(2025, 1, 1, 15, tzinfo=timezone(timedelta(hours=7)))
    assert parse_transaction_timestamp(source) == datetime(2025, 1, 1, 8, tzinfo=UTC)


def test_aware_datetime_utc_overflow_raises_bounded_error():
    source = datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=1)))

    with pytest.raises(TimestampParseError, match="unsupported timestamp") as captured:
        parse_transaction_timestamp(source)

    assert captured.value.args == ("unsupported timestamp",)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("2025-01-01", datetime(2025, 1, 1)),
        ("01/01/2025", datetime(2025, 1, 1)),
        ("2025-01-01 08:30:00", datetime(2025, 1, 1, 8, 30)),
        ("01/01/2025 08:30:00", datetime(2025, 1, 1, 8, 30)),
    ],
)
def test_approved_legacy_value_remains_naive(source, expected):
    result = parse_transaction_timestamp(source)
    assert result == expected
    assert result.tzinfo is None


def test_naive_datetime_preserves_identity():
    source = datetime(2025, 1, 1, 8, 30)
    assert parse_transaction_timestamp(source) is source


@pytest.mark.parametrize(
    "source",
    [
        "",
        "   ",
        " 2025-01-01",
        "2025-01-01 ",
        "not-a-timestamp",
        "2025-02-30",
        "2025-01-01T08:00:00",
        123,
        object(),
        None,
    ],
)
def test_unsupported_value_raises_bounded_error(source):
    with pytest.raises(TimestampParseError, match="unsupported timestamp"):
        parse_transaction_timestamp(source)


@pytest.mark.parametrize(
    "source",
    [
        "2025-01-01X08:00:00+00:00",
        "20250101T080000+00:00",
        "2025-W01-3T08:00:00+00:00",
        "2025-01-01T08:00:00+07",
        "0001-01-01T00:00:00+01:00",
    ],
)
def test_non_contract_iso_value_raises_bounded_error(source):
    with pytest.raises(TimestampParseError, match="unsupported timestamp") as captured:
        parse_transaction_timestamp(source)

    assert captured.value.args == ("unsupported timestamp",)


def test_error_does_not_retain_raw_input():
    raw = "customer-secret-timestamp"
    with pytest.raises(TimestampParseError) as captured:
        parse_transaction_timestamp(raw)
    assert raw not in str(captured.value)
    assert captured.value.args == ("unsupported timestamp",)
