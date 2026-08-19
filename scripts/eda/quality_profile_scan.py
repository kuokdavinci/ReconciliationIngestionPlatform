"""CSV scanning primitives used by the generic quality profile."""

from __future__ import annotations

import csv
import hashlib
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Collection

from scripts.eda.quality_profile_types import QualityProfileSpec


NULL_TOKENS = {"", "na", "n/a", "none", "null", "nan"}


def _is_null(value: str) -> bool:
    return value.strip().lower() in NULL_TOKENS


def _hash_row(row: list[str]) -> bytes:
    return hashlib.blake2b(
        "\x1f".join(row).encode("utf-8"), digest_size=16
    ).digest()


def _parse_timestamp(value: str) -> tuple[datetime, bool]:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    if "T" not in normalized and " " not in normalized:
        raise ValueError("timestamp must include a time")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed, False
    return parsed.astimezone(UTC), True


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _rounded_float(value: float | None) -> float | None:
    return None if value is None else round(value, 8)


def _amount_summary(
    values: list[float],
    minimum: Decimal | None,
    maximum: Decimal | None,
    total: Decimal,
    count: int,
    descriptive_overflow_count: int,
) -> dict[str, Any]:
    q1 = _percentile(values, 0.25)
    median = _percentile(values, 0.50)
    q3 = _percentile(values, 0.75)
    p95 = _percentile(values, 0.95)
    p99 = _percentile(values, 0.99)
    iqr = q3 - q1 if q1 is not None and q3 is not None else None
    upper_bound = q3 + 1.5 * iqr if q3 is not None and iqr is not None else None
    outlier_count = (
        sum(value > upper_bound for value in values)
        if upper_bound is not None
        else 0
    )
    return {
        "count": count,
        "descriptive_count": len(values),
        "descriptive_overflow_count": descriptive_overflow_count,
        "min": _decimal_text(minimum),
        "max": _decimal_text(maximum),
        "mean": _decimal_text(total / Decimal(count)) if count else None,
        "q1": _rounded_float(q1),
        "median": _rounded_float(median),
        "q3": _rounded_float(q3),
        "p95": _rounded_float(p95),
        "p99": _rounded_float(p99),
        "iqr": _rounded_float(iqr),
        "iqr_upper_bound": _rounded_float(upper_bound),
        "outlier_count": outlier_count,
        "outlier_rate": round(outlier_count / len(values), 8) if values else 0.0,
        "quantile_method": "exact_in_memory_float_descriptive_statistics",
        "monetary_authority": "Decimal",
    }


def scan_quality_rows(
    path: Path,
    spec: QualityProfileSpec,
    *,
    distinct_limit: int,
    prefix_rows: int | None,
) -> dict[str, Any]:
    """Scan rows and return internal counters for profile assembly."""

    column_values: dict[str, set[str]] = defaultdict(set)
    column_saturated: set[str] = set()
    samples: dict[str, list[str]] = defaultdict(list)
    null_counts: Counter[str] = Counter()
    invalid_counts: Counter[str] = Counter()
    distributions: dict[str, Counter[str]] = {
        column: Counter() for column in spec.categorical_columns
    }
    row_fingerprints: set[bytes] = set()
    primary_payloads: dict[str, bytes] = {}
    conflicting_primary_keys: set[str] = set()
    duplicate_primary_key_rows = 0
    duplicate_rows: set[int] = set()
    exact_duplicate_rows = 0
    invalid_timestamp_rows: set[int] = set()
    timezone_missing_rows: set[int] = set()
    invalid_amount_rows: set[int] = set()
    negative_amount_rows: set[int] = set()
    missing_required_rows: set[int] = set()
    missing_required_by_field: Counter[str] = Counter()
    invalid_numeric_rows: set[int] = set()
    rejected_rows: set[int] = set()
    amount_values: list[float] = []
    amount_count = 0
    amount_descriptive_overflow_count = 0
    amount_total = Decimal("0")
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    timestamp_min: datetime | None = None
    timestamp_max: datetime | None = None
    timestamp_second_rows = 0
    timestamp_timezone_rows = 0
    timestamp_subsecond_rows = 0
    daily_counts: Counter[str] = Counter()
    row_count = 0
    valid_row_count = 0
    blank_row_count = 0
    malformed_row_count = 0

    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source)
        try:
            headers = [header.strip() for header in next(reader)]
        except StopIteration as exc:
            raise ValueError("Dataset file is empty") from exc

        header_counts = Counter(headers)
        missing_required_columns = sorted(spec.required_columns - set(headers))
        missing_optional_columns = sorted(
            (set(spec.expected_columns) - spec.required_columns) - set(headers)
        )
        unexpected_columns = sorted(set(headers) - set(spec.expected_columns))
        duplicate_headers = sorted(
            header for header, count in header_counts.items() if count > 1
        )

        for row in reader:
            if prefix_rows is not None and row_count >= prefix_rows:
                break
            if not row:
                blank_row_count += 1
                continue
            row_count += 1
            if len(row) != len(headers):
                malformed_row_count += 1
                rejected_rows.add(row_count)
                continue

            valid_row_count += 1
            normalized_row = ["" if _is_null(value) else value.strip() for value in row]
            values = dict(zip(headers, normalized_row, strict=False))
            row_fingerprint = _hash_row(row)
            if row_fingerprint in row_fingerprints:
                exact_duplicate_rows += 1
            row_fingerprints.add(row_fingerprint)
            _collect_column_observations(
                values,
                spec,
                column_values,
                column_saturated,
                samples,
                null_counts,
                distributions,
                distinct_limit,
            )

            primary_key = values.get(spec.primary_key, "").strip()
            if primary_key:
                immutable_payload = _hash_row(
                    [
                        value
                        for column, value in zip(headers, normalized_row, strict=True)
                        if column != spec.primary_key
                    ]
                )
                previous_payload = primary_payloads.get(primary_key)
                if previous_payload is not None:
                    duplicate_primary_key_rows += 1
                    if previous_payload != immutable_payload:
                        conflicting_primary_keys.add(primary_key)
                        rejected_rows.add(row_count)
                        continue
                    duplicate_rows.add(row_count)
                    continue
                primary_payloads[primary_key] = immutable_payload

            _record_required_errors(
                values,
                spec.required_columns,
                missing_required_by_field,
                missing_required_rows,
                rejected_rows,
                row_count,
            )
            (
                timestamp_min,
                timestamp_max,
                timestamp_second_rows,
                timestamp_timezone_rows,
                timestamp_subsecond_rows,
            ) = _record_timestamp(
                values,
                spec.timestamp_column,
                invalid_counts,
                invalid_timestamp_rows,
                timezone_missing_rows,
                rejected_rows,
                daily_counts,
                row_count,
                timestamp_min,
                timestamp_max,
                timestamp_second_rows,
                timestamp_timezone_rows,
                timestamp_subsecond_rows,
            )
            (
                amount_count,
                amount_total,
                amount_min,
                amount_max,
                amount_values,
                amount_descriptive_overflow_count,
            ) = _record_amount(
                values,
                spec.amount_column,
                invalid_counts,
                invalid_amount_rows,
                negative_amount_rows,
                rejected_rows,
                row_count,
                amount_count,
                amount_total,
                amount_min,
                amount_max,
                amount_values,
                amount_descriptive_overflow_count,
            )
            _record_numeric_errors(
                values,
                spec.numeric_columns - {spec.amount_column},
                invalid_counts,
                invalid_numeric_rows,
                row_count,
            )

    return {
        "headers": headers,
        "missing_required_columns": missing_required_columns,
        "missing_optional_columns": missing_optional_columns,
        "unexpected_columns": unexpected_columns,
        "duplicate_headers": duplicate_headers,
        "column_values": column_values,
        "column_saturated": column_saturated,
        "samples": samples,
        "null_counts": null_counts,
        "invalid_counts": invalid_counts,
        "distributions": distributions,
        "conflicting_primary_keys": conflicting_primary_keys,
        "duplicate_primary_key_rows": duplicate_primary_key_rows,
        "duplicate_rows": duplicate_rows,
        "exact_duplicate_rows": exact_duplicate_rows,
        "invalid_timestamp_rows": invalid_timestamp_rows,
        "timezone_missing_rows": timezone_missing_rows,
        "invalid_amount_rows": invalid_amount_rows,
        "negative_amount_rows": negative_amount_rows,
        "missing_required_rows": missing_required_rows,
        "missing_required_by_field": missing_required_by_field,
        "invalid_numeric_rows": invalid_numeric_rows,
        "rejected_rows": rejected_rows,
        "timestamp_min": timestamp_min,
        "timestamp_max": timestamp_max,
        "timestamp_second_rows": timestamp_second_rows,
        "timestamp_timezone_rows": timestamp_timezone_rows,
        "timestamp_subsecond_rows": timestamp_subsecond_rows,
        "daily_counts": daily_counts,
        "amount_summary": _amount_summary(
            amount_values,
            amount_min,
            amount_max,
            amount_total,
            amount_count,
            amount_descriptive_overflow_count,
        ),
        "row_count": row_count,
        "valid_row_count": valid_row_count,
        "blank_row_count": blank_row_count,
        "malformed_row_count": malformed_row_count,
    }


def _collect_column_observations(
    values: dict[str, str],
    spec: QualityProfileSpec,
    column_values: dict[str, set[str]],
    column_saturated: set[str],
    samples: dict[str, list[str]],
    null_counts: Counter[str],
    distributions: dict[str, Counter[str]],
    distinct_limit: int,
) -> None:
    for column, clean_value in values.items():
        if not clean_value:
            null_counts[column] += 1
            continue
        if len(samples[column]) < 5 and clean_value not in samples[column]:
            samples[column].append(clean_value)
        if clean_value not in column_values[column]:
            if len(column_values[column]) < distinct_limit:
                column_values[column].add(clean_value)
            else:
                column_saturated.add(column)
        if column in distributions:
            distributions[column][clean_value] += 1


def _record_required_errors(
    values: dict[str, str],
    required_columns: frozenset[str],
    missing_by_field: Counter[str],
    missing_rows: set[int],
    rejected_rows: set[int],
    row_number: int,
) -> None:
    row_has_error = False
    for column in required_columns:
        if column not in values or _is_null(values[column]):
            missing_by_field[column] += 1
            row_has_error = True
    if row_has_error:
        missing_rows.add(row_number)
        rejected_rows.add(row_number)


def _record_timestamp(
    values: dict[str, str],
    column: str | None,
    invalid_counts: Counter[str],
    invalid_rows: set[int],
    timezone_missing_rows: set[int],
    rejected_rows: set[int],
    daily_counts: Counter[str],
    row_number: int,
    minimum: datetime | None,
    maximum: datetime | None,
    second_rows: int,
    timezone_rows: int,
    subsecond_rows: int,
) -> tuple[datetime | None, datetime | None, int, int, int]:
    if column is None:
        return minimum, maximum, second_rows, timezone_rows, subsecond_rows
    timestamp_text = values.get(column, "").strip()
    if not timestamp_text:
        return minimum, maximum, second_rows, timezone_rows, subsecond_rows
    try:
        timestamp, has_timezone = _parse_timestamp(timestamp_text)
    except (TypeError, ValueError):
        invalid_counts[column] += 1
        invalid_rows.add(row_number)
        rejected_rows.add(row_number)
        return minimum, maximum, second_rows, timezone_rows, subsecond_rows
    if not has_timezone:
        timezone_missing_rows.add(row_number)
        rejected_rows.add(row_number)
        return minimum, maximum, second_rows, timezone_rows, subsecond_rows
    timezone_rows += 1
    if timestamp.microsecond == 0:
        second_rows += 1
    else:
        subsecond_rows += 1
    daily_counts[timestamp.date().isoformat()] += 1
    return (
        min(minimum, timestamp) if minimum else timestamp,
        max(maximum, timestamp) if maximum else timestamp,
        second_rows,
        timezone_rows,
        subsecond_rows,
    )


def _record_amount(
    values: dict[str, str],
    column: str | None,
    invalid_counts: Counter[str],
    invalid_rows: set[int],
    negative_rows: set[int],
    rejected_rows: set[int],
    row_number: int,
    count: int,
    total: Decimal,
    minimum: Decimal | None,
    maximum: Decimal | None,
    descriptive_values: list[float],
    overflow_count: int,
) -> tuple[int, Decimal, Decimal | None, Decimal | None, list[float], int]:
    if column is None:
        return count, total, minimum, maximum, descriptive_values, overflow_count
    amount_text = values.get(column, "").strip()
    if not amount_text:
        return count, total, minimum, maximum, descriptive_values, overflow_count
    try:
        amount = Decimal(amount_text)
        if not amount.is_finite():
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        invalid_counts[column] += 1
        invalid_rows.add(row_number)
        rejected_rows.add(row_number)
        return count, total, minimum, maximum, descriptive_values, overflow_count

    count += 1
    total += amount
    minimum = min(minimum, amount) if minimum is not None else amount
    maximum = max(maximum, amount) if maximum is not None else amount
    if amount < 0:
        negative_rows.add(row_number)
        invalid_rows.add(row_number)
        rejected_rows.add(row_number)
    try:
        amount_float = float(amount)
    except (OverflowError, ValueError):
        overflow_count += 1
    else:
        if math.isfinite(amount_float):
            descriptive_values.append(amount_float)
        else:
            overflow_count += 1
    return count, total, minimum, maximum, descriptive_values, overflow_count


def _record_numeric_errors(
    values: dict[str, str],
    columns: Collection[str],
    invalid_counts: Counter[str],
    invalid_rows: set[int],
    row_number: int,
) -> None:
    for column in columns:
        value = values.get(column, "").strip()
        if not value:
            continue
        try:
            parsed = Decimal(value)
            if not parsed.is_finite():
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            invalid_counts[column] += 1
            invalid_rows.add(row_number)
