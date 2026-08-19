"""Contract tests for the generic ingestion quality profile."""

import json
from pathlib import Path

import pytest

from scripts.eda.profile_report import render_markdown, write_profile
from scripts.eda.quality_profile import (
    QualityProfileSpec,
    build_quality_profile,
)


HEADER = "transaction_id,timestamp,amount,currency,category"
DEFAULT_ROW = "TX1,2025-01-01T00:00:01+00:00,10.25,USD,retail"
SPEC = QualityProfileSpec(
    name="generic-transactions",
    expected_columns=tuple(HEADER.split(",")),
    required_columns=frozenset({"transaction_id", "timestamp", "amount", "currency"}),
    primary_key="transaction_id",
    identifier_columns=frozenset({"transaction_id"}),
    categorical_columns=frozenset({"currency", "category"}),
    numeric_columns=frozenset({"amount"}),
    datetime_columns=frozenset({"timestamp"}),
    amount_column="amount",
    timestamp_column="timestamp",
)


def _write_fixture(path: Path, *rows: str, header: str = HEADER) -> None:
    path.write_text("\n".join((header, *rows)) + "\n", encoding="utf-8")


def _row_with(**changes: str) -> str:
    values = dict(zip(HEADER.split(","), DEFAULT_ROW.split(","), strict=True))
    values.update(changes)
    return ",".join(values[column] for column in HEADER.split(","))


def _rules(profile: dict) -> dict[str, dict]:
    return {result["rule_code"]: result for result in profile["rule_results"]}


def test_clean_profile_is_generic_and_passes(tmp_path: Path) -> None:
    source = tmp_path / "transactions.csv"
    _write_fixture(source, DEFAULT_ROW)

    profile = build_quality_profile(source, SPEC)
    rules = _rules(profile)

    assert profile["profile_version"] == 3
    assert profile["dataset"] == {
        "name": "generic-transactions",
        "purpose": "ingestion-data-quality-profile",
    }
    assert profile["quality"]["valid_rows"] == 1
    assert profile["quality"]["rejected_rows"] == 0
    assert profile["decision"] == "PASS"
    assert "AMOUNT_OUTLIER" not in rules
    assert profile["observations"]["amount"]["outlier_count"] == 0


@pytest.mark.parametrize("field", ["transaction_id", "timestamp", "amount", "currency"])
def test_missing_required_value_is_rejected(tmp_path: Path, field: str) -> None:
    source = tmp_path / "transactions.csv"
    _write_fixture(source, _row_with(**{field: ""}))

    profile = build_quality_profile(source, SPEC)
    rule = _rules(profile)[f"REQ_{field.upper()}"]

    assert rule["result"] == "FAIL"
    assert rule["action"] == "RECORD_REJECTED"
    assert profile["quality"]["rejected_rows"] == 1
    assert profile["decision"] == "FAIL"


@pytest.mark.parametrize("null_token", ["", "na", "n/a", "none", "null", "nan", "NULL"])
def test_null_tokens_are_normalized_before_validation(
    tmp_path: Path, null_token: str
) -> None:
    source = tmp_path / "transactions.csv"
    _write_fixture(
        source,
        _row_with(
            transaction_id=null_token,
            timestamp=null_token,
            amount=null_token,
            currency=null_token,
            category=null_token,
        ),
    )

    profile = build_quality_profile(source, SPEC)
    columns = {column["name"]: column for column in profile["schema"]["columns"]}

    assert profile["quality"]["missing_required_rows"] == 1
    assert profile["quality"]["invalid_timestamp_rows"] == 0
    assert profile["quality"]["invalid_amount_rows"] == 0
    assert columns["category"]["null_count"] == 1
    assert profile["decision"] == "FAIL"


def test_malformed_rows_and_physical_blank_rows_are_distinguished(tmp_path: Path) -> None:
    source = tmp_path / "transactions.csv"
    _write_fixture(source, DEFAULT_ROW, "", "TX2,too,few")

    profile = build_quality_profile(source, SPEC)

    assert profile["quality"]["input_rows"] == 2
    assert profile["quality"]["blank_rows"] == 1
    assert profile["quality"]["malformed_rows"] == 1
    assert profile["quality"]["valid_rows"] == 1
    assert _rules(profile)["MALFORMED_ROW"]["result"] == "FAIL"
    assert profile["decision"] == "FAIL"


def test_timestamp_format_timezone_and_precision_are_separate_signals(
    tmp_path: Path,
) -> None:
    source = tmp_path / "transactions.csv"
    _write_fixture(
        source,
        _row_with(transaction_id="BAD", timestamp="not-a-timestamp"),
        _row_with(transaction_id="NAIVE", timestamp="2025-01-01T00:00:01"),
        _row_with(transaction_id="SUBSECOND", timestamp="2025-01-01T00:00:01.123+00:00"),
    )

    profile = build_quality_profile(source, SPEC)
    rules = _rules(profile)

    assert profile["quality"]["invalid_timestamp_rows"] == 1
    assert profile["observations"]["timestamp_precision"] == {
        "second_rows": 0,
        "timezone_rows": 1,
        "timezone_missing_rows": 1,
        "subsecond_rows": 1,
    }
    assert rules["INVALID_TIMESTAMP"]["result"] == "FAIL"
    assert rules["TIMESTAMP_TIMEZONE_REQUIRED"]["result"] == "FAIL"
    assert rules["TIMESTAMP_PRECISION_DRIFT"]["result"] == "REVIEW"
    assert profile["decision"] == "FAIL"


@pytest.mark.parametrize(
    ("amount", "expected_decision", "expected_rejected"),
    [("not-a-number", "FAIL", 1), ("-0.01", "FAIL", 1), ("0", "PASS", 0)],
)
def test_amount_contract_rejects_only_invalid_or_negative_values(
    tmp_path: Path, amount: str, expected_decision: str, expected_rejected: int
) -> None:
    source = tmp_path / "transactions.csv"
    _write_fixture(source, _row_with(amount=amount))

    profile = build_quality_profile(source, SPEC)

    assert profile["quality"]["rejected_rows"] == expected_rejected
    assert _rules(profile)["INVALID_AMOUNT"]["result"] == (
        "FAIL" if expected_rejected else "PASS"
    )
    assert profile["quality"]["negative_amount_rows"] == (1 if amount == "-0.01" else 0)
    assert profile["decision"] == expected_decision


def test_decimal_amount_is_authoritative_when_float_descriptive_stats_overflow(
    tmp_path: Path,
) -> None:
    source = tmp_path / "transactions.csv"
    _write_fixture(source, _row_with(amount="1e10000"))

    profile = build_quality_profile(source, SPEC)
    amount = profile["observations"]["amount"]

    assert amount["count"] == 1
    assert amount["descriptive_count"] == 0
    assert amount["descriptive_overflow_count"] == 1
    assert amount["min"] == "1" + ("0" * 10_000)
    assert _rules(profile)["AMOUNT_DESCRIPTIVE_OVERFLOW"]["result"] == "WARNING"
    assert profile["decision"] == "REVIEW"


def test_equivalent_and_conflicting_primary_key_rows_are_distinguished(
    tmp_path: Path,
) -> None:
    source = tmp_path / "transactions.csv"
    _write_fixture(source, DEFAULT_ROW, DEFAULT_ROW, _row_with(amount="11.25"))

    profile = build_quality_profile(source, SPEC)
    rules = _rules(profile)

    assert profile["quality"]["duplicate_rows"] == 1
    assert profile["quality"]["rejected_rows"] == 1
    assert rules["UNIQUE_TRANSACTION_ID"]["action"] == "DUPLICATE"
    assert rules["CONFLICTING_DUPLICATE"]["action"] == "QUARANTINE_CANDIDATE"
    assert profile["decision"] == "FAIL"


@pytest.mark.parametrize(
    ("header", "rule_code", "decision"),
    [
        (
            ",".join(column for column in HEADER.split(",") if column != "currency"),
            "SCHEMA_REQUIRED_COLUMNS",
            "FAIL",
        ),
        (HEADER.replace("currency", "currency,currency"), "SCHEMA_REQUIRED_COLUMNS", "FAIL"),
        (HEADER.replace(",category", ""), "SCHEMA_DRIFT", "REVIEW"),
        (f"{HEADER},new_field", "SCHEMA_DRIFT", "REVIEW"),
    ],
)
def test_schema_required_and_drift_rules_are_deterministic(
    tmp_path: Path, header: str, rule_code: str, decision: str
) -> None:
    source = tmp_path / "transactions.csv"
    values = DEFAULT_ROW.split(",")
    if header.count("currency") == 2:
        row = ",".join((*values[:3], values[3], values[3], values[4]))
    elif "category" not in header:
        row = ",".join(values[:-1])
    elif "new_field" in header:
        row = f"{DEFAULT_ROW},new"
    else:
        row = DEFAULT_ROW
    _write_fixture(source, row, header=header)

    profile = build_quality_profile(source, SPEC)
    rule = _rules(profile)[rule_code]

    assert rule["result"] == ("FAIL" if decision == "FAIL" else "REVIEW")
    assert profile["decision"] == decision


def test_statistical_outliers_are_observations_not_quality_gate_rules(tmp_path: Path) -> None:
    source = tmp_path / "transactions.csv"
    _write_fixture(
        source,
        _row_with(transaction_id="ONE", amount="1"),
        _row_with(transaction_id="TWO", amount="1"),
        _row_with(transaction_id="THREE", amount="1"),
        _row_with(transaction_id="OUTLIER", amount="100"),
    )

    profile = build_quality_profile(source, SPEC)

    assert profile["observations"]["amount"]["outlier_count"] == 1
    assert "AMOUNT_OUTLIER" not in _rules(profile)
    assert profile["decision"] == "PASS"


def test_profile_writes_json_and_markdown_without_dataset_specific_copy(
    tmp_path: Path,
) -> None:
    source = tmp_path / "transactions.csv"
    _write_fixture(source, DEFAULT_ROW)

    json_path, markdown_path = write_profile(source, tmp_path / "profiles", SPEC)

    json_text = json_path.read_text(encoding="utf-8")
    payload = json.loads(json_text)
    markdown = markdown_path.read_text(encoding="utf-8")
    assert payload["profile_version"] == 3
    assert "SCHEMA_DRIFT" in {rule["rule_code"] for rule in payload["rule_results"]}
    assert "\n" not in json_text.rstrip("\n")
    assert "TIMESTAMP_TIMEZONE_REQUIRED" in markdown
    assert "## Rule Results" in markdown
    assert "Fraud Detection" not in render_markdown(payload)


def test_fraud_dataset_adapter_uses_source_schema_without_fraud_quality_rules(
    tmp_path: Path,
) -> None:
    from scripts.eda.fraud_detection_dataset import FRAUD_DATASET_SPEC

    source = tmp_path / "fraud.csv"
    header = ",".join(FRAUD_DATASET_SPEC.expected_columns)
    row = ",".join(
        [
            "TX1",
            "2025-01-01T00:00:01+00:00",
            "C1",
            "CARD1",
            "DEV1",
            "10.0.0.1",
            "M1",
            "retail",
            "US",
            "City",
            "1.0",
            "2.0",
            "purchase",
            "10.25",
            "USD",
            "0",
            "",
        ]
    )
    _write_fixture(source, row, header=header)

    profile = build_quality_profile(source, FRAUD_DATASET_SPEC)
    rule_codes = {rule["rule_code"] for rule in profile["rule_results"]}

    assert profile["dataset"]["name"] == "Fraud Detection Dataset"
    assert not any(code.startswith("FRAUD_") for code in rule_codes)
    assert "COORDINATE_RANGE" not in rule_codes
    assert "CARD_CUSTOMER_CONSISTENCY" not in rule_codes
    assert profile["decision"] == "PASS"
