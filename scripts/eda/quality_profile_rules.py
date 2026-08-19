"""Generic rule-result assembly for quality profiles."""

from __future__ import annotations

from typing import Any

from scripts.eda.quality_profile_types import QualityProfileSpec


def _rule(
    code: str,
    *,
    field: str | None,
    severity: str,
    result: str,
    actual: Any,
    expected: Any,
    action: str,
) -> dict[str, Any]:
    return {
        "rule_code": code,
        "field": field,
        "severity": severity,
        "result": result,
        "actual": actual,
        "expected": expected,
        "action": action,
    }


def build_rule_results(spec: QualityProfileSpec, scan: dict[str, Any]) -> list[dict[str, Any]]:
    schema_required_failure = bool(
        scan["missing_required_columns"] or scan["duplicate_headers"]
    )
    schema_drift = bool(scan["missing_optional_columns"] or scan["unexpected_columns"])
    precision_drift = scan["timestamp_subsecond_rows"] > 0
    rules = [
        _rule(
            "SCHEMA_REQUIRED_COLUMNS",
            field=None,
            severity="FATAL",
            result="FAIL" if schema_required_failure else "PASS",
            actual={
                "missing_required": scan["missing_required_columns"],
                "duplicate_headers": scan["duplicate_headers"],
            },
            expected={"missing_required": [], "duplicate_headers": []},
            action="BATCH_FATAL" if schema_required_failure else "CONTINUE",
        ),
        _rule(
            "SCHEMA_DRIFT",
            field=None,
            severity="WARNING",
            result="REVIEW" if schema_drift else "PASS",
            actual={
                "missing_optional": scan["missing_optional_columns"],
                "unexpected": scan["unexpected_columns"],
            },
            expected={"missing_optional": [], "unexpected": []},
            action="MAPPING_REVIEW" if schema_drift else "CONTINUE",
        ),
        _rule(
            "MALFORMED_ROW",
            field=None,
            severity="RECORD",
            result="FAIL" if scan["malformed_row_count"] else "PASS",
            actual=scan["malformed_row_count"],
            expected=0,
            action="RECORD_REJECTED" if scan["malformed_row_count"] else "ACCEPT",
        ),
    ]
    rules.extend(_required_rules(spec, scan))
    rules.extend(_duplicate_rules(spec, scan))
    if spec.timestamp_column:
        rules.extend(_timestamp_rules(spec, scan, precision_drift))
    if spec.amount_column:
        rules.extend(_amount_rules(spec, scan))
    if spec.numeric_columns - {spec.amount_column}:
        rules.append(_numeric_rule(spec, scan))
    return rules


def determine_decision(scan: dict[str, Any]) -> str:
    if scan["missing_required_columns"] or scan["duplicate_headers"] or scan["rejected_rows"]:
        return "FAIL"
    if (
        scan["missing_optional_columns"]
        or scan["unexpected_columns"]
        or scan["timestamp_subsecond_rows"]
        or scan["amount_summary"]["descriptive_overflow_count"]
        or scan["invalid_numeric_rows"]
    ):
        return "REVIEW"
    return "PASS"


def _required_rules(spec: QualityProfileSpec, scan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _rule(
            f"REQ_{column.upper()}",
            field=column,
            severity="RECORD",
            result="FAIL" if scan["missing_required_by_field"][column] else "PASS",
            actual=scan["missing_required_by_field"][column],
            expected=0,
            action="RECORD_REJECTED"
            if scan["missing_required_by_field"][column]
            else "ACCEPT",
        )
        for column in sorted(spec.required_columns)
    ]


def _duplicate_rules(spec: QualityProfileSpec, scan: dict[str, Any]) -> list[dict[str, Any]]:
    duplicate_rows = scan["duplicate_rows"]
    conflicting = scan["conflicting_primary_keys"]
    return [
        _rule(
            f"UNIQUE_{spec.primary_key.upper()}",
            field=spec.primary_key,
            severity="RECORD",
            result="PASS" if not duplicate_rows else "WARNING",
            actual=len(duplicate_rows),
            expected=0,
            action="ACCEPT" if not duplicate_rows else "DUPLICATE",
        ),
        _rule(
            "CONFLICTING_DUPLICATE",
            field=spec.primary_key,
            severity="RECORD",
            result="PASS" if not conflicting else "FAIL",
            actual=len(conflicting),
            expected=0,
            action="ACCEPT" if not conflicting else "QUARANTINE_CANDIDATE",
        ),
    ]


def _timestamp_rules(
    spec: QualityProfileSpec,
    scan: dict[str, Any],
    precision_drift: bool,
) -> list[dict[str, Any]]:
    invalid = scan["invalid_timestamp_rows"]
    timezone_missing = scan["timezone_missing_rows"]
    return [
        _rule(
            "INVALID_TIMESTAMP",
            field=spec.timestamp_column,
            severity="RECORD",
            result="PASS" if not invalid else "FAIL",
            actual=len(invalid),
            expected=0,
            action="ACCEPT" if not invalid else "RECORD_REJECTED",
        ),
        _rule(
            "TIMESTAMP_TIMEZONE_REQUIRED",
            field=spec.timestamp_column,
            severity="RECORD",
            result="FAIL" if timezone_missing else "PASS",
            actual=len(timezone_missing),
            expected=0,
            action="RECORD_REJECTED" if timezone_missing else "ACCEPT",
        ),
        _rule(
            "TIMESTAMP_PRECISION_DRIFT",
            field=spec.timestamp_column,
            severity="WARNING",
            result="REVIEW" if precision_drift else "PASS",
            actual=scan["timestamp_subsecond_rows"],
            expected=0,
            action="REVIEW_ONLY" if precision_drift else "ACCEPT",
        ),
    ]


def _amount_rules(spec: QualityProfileSpec, scan: dict[str, Any]) -> list[dict[str, Any]]:
    invalid = scan["invalid_amount_rows"]
    negative = scan["negative_amount_rows"]
    overflow = scan["amount_summary"]["descriptive_overflow_count"]
    return [
        _rule(
            "INVALID_AMOUNT",
            field=spec.amount_column,
            severity="RECORD",
            result="PASS" if not invalid else "FAIL",
            actual={"invalid_rows": len(invalid), "negative_rows": len(negative)},
            expected={"invalid_rows": 0, "negative_rows": 0},
            action="ACCEPT" if not invalid else "RECORD_REJECTED",
        ),
        _rule(
            "AMOUNT_DESCRIPTIVE_OVERFLOW",
            field=spec.amount_column,
            severity="WARNING",
            result="WARNING" if overflow else "PASS",
            actual=overflow,
            expected=0,
            action="REVIEW_ONLY" if overflow else "ACCEPT",
        ),
    ]


def _numeric_rule(spec: QualityProfileSpec, scan: dict[str, Any]) -> dict[str, Any]:
    columns = spec.numeric_columns - {spec.amount_column}
    invalid_rows = scan["invalid_numeric_rows"]
    return _rule(
        "INVALID_NUMERIC_VALUES",
        field=None,
        severity="WARNING",
        result="REVIEW" if invalid_rows else "PASS",
        actual={
            "rows": len(invalid_rows),
            "by_field": {
                column: scan["invalid_counts"][column] for column in sorted(columns)
            },
        },
        expected=0,
        action="REVIEW_ONLY" if invalid_rows else "ACCEPT",
    )
