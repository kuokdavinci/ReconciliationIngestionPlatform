"""Unit tests for the Sprint 3 fraud-dataset benchmark helpers."""

from pathlib import Path
from typing import Any

import pytest

from scripts.benchmark_fraud_detection import (
    BENCHMARK_CONFIG_VERSION,
    BENCHMARK_WORKFLOW,
    _case_meets_acceptance,
    build_mapping_document,
    build_benchmark_config,
    redact_mongodb_url,
    render_markdown,
    write_prefix_csv,
)


def test_mapping_document_covers_canonical_fields_and_source_lineage() -> None:
    document = build_mapping_document()

    assert document["workflowType"] == BENCHMARK_WORKFLOW
    assert document["startRow"] == 2
    mappings = {mapping["path"]: mapping for mapping in document["fieldMappings"]}
    assert mappings["id"] == {
        "path": "id",
        "column": 1,
        "type": "STRING",
        "required": True,
    }
    assert mappings["amount"]["type"] == "DECIMAL"
    assert mappings["currency"]["column"] == 15
    assert mappings["status"]["constant"] == "SUCCESS"
    assert document["configVersion"] == "sprint3-fraud-detection-v2"
    assert mappings["transDate"] == {
        "path": "transDate",
        "column": 2,
        "type": "DATE",
        "required": True,
    }
    assert "extra.sourceTimestamp" not in mappings
    assert "extra.fraudType" not in mappings


def test_write_prefix_csv_copies_header_and_requested_rows(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text("id,amount\n1,10\n2,20\n3,30\n", encoding="utf-8")
    output = tmp_path / "prefix.csv"

    rows = write_prefix_csv(source, output, 2)

    assert rows == 2
    assert output.read_text(encoding="utf-8") == "id,amount\n1,10\n2,20\n"


def test_benchmark_config_can_run_full_file_with_two_workers() -> None:
    config = build_benchmark_config(
        batch_size=100_000,
        write_workers=2,
        full_only=True,
    )

    assert config.batch_size == 100_000
    assert config.write_workers == 2
    assert config.cases == (None,)


def test_benchmark_config_rejects_non_positive_tuning_values() -> None:
    with pytest.raises(ValueError, match="batch_size"):
        build_benchmark_config(batch_size=0, write_workers=2, full_only=True)
    with pytest.raises(ValueError, match="write_workers"):
        build_benchmark_config(batch_size=100_000, write_workers=0, full_only=True)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, True),
        ({"input_rows": 0, "persisted_rows": 0}, False),
        ({"persisted_rows": 19}, False),
        ({"failed_rows": 1}, False),
        ({"duplicate_rows": 1}, False),
        ({"quality_decision": "REVIEW"}, False),
        ({"orchestration_action": "HOLD_FOR_REVIEW"}, False),
        ({"outcome": "FAILED"}, False),
    ],
)
def test_case_acceptance_requires_exact_clean_ingestion(
    overrides: dict[str, Any], expected: bool
) -> None:
    case: dict[str, Any] = {
        "input_rows": 20,
        "persisted_rows": 20,
        "failed_rows": 0,
        "duplicate_rows": 0,
        "quality_decision": "PASS",
        "orchestration_action": "CONTINUE",
        "outcome": "INGESTED",
    }
    case.update(overrides)

    assert _case_meets_acceptance(case) is expected


def _render_report() -> dict[str, Any]:
    return {
        "status": "completed",
        "dataset": {"path": "fixture.csv", "sha256": "fixture-sha"},
        "environment": {"mongodb": "configured", "db_name": "fixture"},
        "cleanup": "benchmark records and mapping removed",
        "configuration": {
            "config_version": BENCHMARK_CONFIG_VERSION,
            "batch_size": 20,
            "write_workers": 1,
        },
        "cases": [],
    }


def test_markdown_uses_report_config_version() -> None:
    markdown = render_markdown(_render_report())

    assert f"- Mapping: `{BENCHMARK_CONFIG_VERSION}`" in markdown
    assert "sprint3-fraud-detection-v1" not in markdown
    assert "`extra.sourceTimestamp`" not in markdown


def test_redact_mongodb_url_hides_password() -> None:
    redacted = redact_mongodb_url(
        "mongodb://admin:secret@example.test:27017/reconciliation?authSource=admin"
    )

    assert redacted == (
        "mongodb://admin:***@example.test:27017/reconciliation?authSource=admin"
    )
    assert "secret" not in redacted
