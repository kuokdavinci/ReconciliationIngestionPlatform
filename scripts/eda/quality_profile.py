"""Public API for reusable, deterministic ingestion quality profiles."""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.eda.quality_profile_rules import build_rule_results, determine_decision
from scripts.eda.quality_profile_scan import scan_quality_rows
from scripts.eda.quality_profile_types import QualityProfileSpec, validate_spec

__all__ = ["QualityProfileSpec", "build_quality_profile"]


def build_quality_profile(
    path: Path,
    spec: QualityProfileSpec,
    *,
    distinct_limit: int = 100_000,
    prefix_rows: int | None = None,
) -> dict[str, Any]:
    """Build a deterministic quality profile without loading a DataFrame."""

    _validate_inputs(path, spec, distinct_limit, prefix_rows)
    scan = scan_quality_rows(
        path,
        spec,
        distinct_limit=distinct_limit,
        prefix_rows=prefix_rows,
    )
    return _assemble_profile(path, spec, prefix_rows, scan)


def _validate_inputs(
    path: Path,
    spec: QualityProfileSpec,
    distinct_limit: int,
    prefix_rows: int | None,
) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Dataset file not found: {path}")
    if distinct_limit < 1:
        raise ValueError("distinct_limit must be positive")
    if prefix_rows is not None and prefix_rows < 1:
        raise ValueError("prefix_rows must be positive when provided")
    validate_spec(spec)


def _assemble_profile(
    path: Path,
    spec: QualityProfileSpec,
    prefix_rows: int | None,
    scan: dict[str, Any],
) -> dict[str, Any]:
    headers = scan["headers"]
    null_counts: Counter[str] = scan["null_counts"]
    column_values: dict[str, set[str]] = scan["column_values"]
    column_saturated: set[str] = scan["column_saturated"]
    samples: dict[str, list[str]] = scan["samples"]
    invalid_counts: Counter[str] = scan["invalid_counts"]
    row_count = scan["row_count"]
    valid_row_count = scan["valid_row_count"]
    return {
        "profile_version": 3,
        "dataset": {"name": spec.name, "purpose": "ingestion-data-quality-profile"},
        "file": {
            "name": path.name,
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "row_count": row_count,
            "valid_row_count": valid_row_count,
            "prefix_rows": prefix_rows,
        },
        "schema": {
            "column_count": len(headers),
            "drift": {
                "missing_required": scan["missing_required_columns"],
                "missing_optional": scan["missing_optional_columns"],
                "unexpected": scan["unexpected_columns"],
                "duplicate_headers": scan["duplicate_headers"],
            },
            "columns": [
                {
                    "name": column,
                    "role": _role_for(column, spec),
                    "null_count": null_counts[column],
                    "null_rate": round(null_counts[column] / valid_row_count, 8)
                    if valid_row_count
                    else 0.0,
                    "distinct_count": len(column_values[column]),
                    "distinct_count_exact": column not in column_saturated,
                    "invalid_count": invalid_counts[column],
                    "sample_values": samples[column],
                }
                for column in headers
            ],
        },
        "quality": _quality_summary(scan, spec),
        "observations": _observations_summary(scan),
        "rule_results": build_rule_results(spec, scan),
        "quality_score": round(100 * (row_count - len(scan["rejected_rows"])) / row_count, 4)
        if row_count
        else 0.0,
        "decision": determine_decision(scan),
        "limitations": [
            "Statistical observations are descriptive and do not establish business thresholds.",
            "Duplicate behavior is scoped to this file; persistence idempotency needs its own contract.",
            "Required fields, timestamp precision, and negative-amount policy require source-contract approval.",
        ],
    }


def _quality_summary(scan: dict[str, Any], spec: QualityProfileSpec) -> dict[str, Any]:
    return {
        "input_rows": scan["row_count"],
        "valid_rows": scan["row_count"]
        - len(scan["rejected_rows"])
        - len(scan["duplicate_rows"]),
        "rejected_rows": len(scan["rejected_rows"]),
        "duplicate_rows": len(scan["duplicate_rows"]),
        "blank_rows": scan["blank_row_count"],
        "malformed_rows": scan["malformed_row_count"],
        "null_cell_count": sum(scan["null_counts"].values()),
        "missing_required_rows": len(scan["missing_required_rows"]),
        "missing_required_by_field": {
            column: scan["missing_required_by_field"][column]
            for column in sorted(spec.required_columns)
        },
        "invalid_timestamp_rows": len(scan["invalid_timestamp_rows"]),
        "invalid_amount_rows": len(scan["invalid_amount_rows"]),
        "negative_amount_rows": len(scan["negative_amount_rows"]),
        "invalid_numeric_rows": len(scan["invalid_numeric_rows"]),
        "exact_duplicate_rows": scan["exact_duplicate_rows"],
        "duplicate_primary_key_rows": scan["duplicate_primary_key_rows"],
        "conflicting_primary_key_groups": len(scan["conflicting_primary_keys"]),
    }


def _observations_summary(scan: dict[str, Any]) -> dict[str, Any]:
    daily_counts: Counter[str] = scan["daily_counts"]
    days = sorted(daily_counts)
    counts = [float(daily_counts[day]) for day in days]
    return {
        "timestamp_range": {
            "min": scan["timestamp_min"].isoformat() if scan["timestamp_min"] else None,
            "max": scan["timestamp_max"].isoformat() if scan["timestamp_max"] else None,
        },
        "timestamp_precision": {
            "second_rows": scan["timestamp_second_rows"],
            "timezone_rows": scan["timestamp_timezone_rows"],
            "timezone_missing_rows": len(scan["timezone_missing_rows"]),
            "subsecond_rows": scan["timestamp_subsecond_rows"],
        },
        "temporal": {
            "daily_counts": {day: daily_counts[day] for day in days},
            "day_count": len(days),
            "first_day": days[0] if days else None,
            "first_day_rows": daily_counts[days[0]] if days else 0,
            "last_day": days[-1] if days else None,
            "last_day_rows": daily_counts[days[-1]] if days else 0,
            "daily_min": min(daily_counts.values()) if days else None,
            "daily_median": _percentile(counts, 0.5),
            "daily_max": max(daily_counts.values()) if days else None,
        },
        "amount": scan["amount_summary"],
        "distributions": {
            name: dict(values) for name, values in scan["distributions"].items()
        },
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = lower if position == lower else lower + 1
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _role_for(column: str, spec: QualityProfileSpec) -> str:
    if column in spec.identifier_columns:
        return "identifier"
    if column in spec.categorical_columns:
        return "categorical"
    if column in spec.numeric_columns:
        return "numeric"
    if column in spec.datetime_columns:
        return "datetime"
    return "unknown"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
