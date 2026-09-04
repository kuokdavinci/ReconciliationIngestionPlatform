"""Unit tests for the Sprint 3 fraud-dataset benchmark helpers."""

from pathlib import Path
from typing import Any

import pytest

from scripts.benchmark_fraud_detection import (
    BENCHMARK_CONFIG_VERSION,
    BENCHMARK_WORKFLOW,
    _case_meets_acceptance,
    _ensure_postgres_quiet,
    build_mapping_document,
    build_benchmark_config,
    aggregate_samples,
    all_samples_meet_acceptance,
    optimization_gate,
    peak_rss_bytes,
    redact_mongodb_url,
    render_markdown,
    rotate_variants,
    summarize_explain_plan,
    VARIANT_MATRIX,
    write_prefix_csv,
)
from src.infrastructure.partner_transaction.repository import (
    build_partner_transaction_classify_sql,
    build_partner_transaction_stage_sql,
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


def _clean_sample(**overrides: Any) -> dict[str, Any]:
    sample = {
        "input_rows": 100_000,
        "persisted_rows": 100_000,
        "duplicate_rows": 0,
        "failed_rows": 0,
        "quarantined_rows": 0,
        "quality_decision": "PASS",
        "orchestration_action": "CONTINUE",
        "outcome": "INGESTED",
        "wall_clock_ms": 100.0,
        "throughput_rows_per_second": 1_000.0,
        "peak_rss_bytes": 100,
    }
    sample.update(overrides)
    return sample


def test_review_aggregation_keeps_raw_samples_and_reports_median_mad() -> None:
    aggregate = aggregate_samples(
        [
            _clean_sample(wall_clock_ms=100.0, peak_rss_bytes=100),
            _clean_sample(wall_clock_ms=110.0, peak_rss_bytes=120),
            _clean_sample(wall_clock_ms=130.0, peak_rss_bytes=140),
        ]
    )

    assert aggregate["sample_count"] == 3
    assert aggregate["wall_clock_ms"] == {
        "median": 110.0,
        "mad": 10.0,
        "samples": [100.0, 110.0, 130.0],
    }
    assert aggregate["peak_rss_bytes"]["max"] == 140


def test_rss_gate_applies_to_every_sample() -> None:
    assert all_samples_meet_acceptance([_clean_sample(peak_rss_bytes=999)], rss_cap_bytes=1000)
    assert not all_samples_meet_acceptance(
        [_clean_sample(), _clean_sample(peak_rss_bytes=1001)], rss_cap_bytes=1000
    )


def test_optimization_gate_accepts_latency_or_memory_win() -> None:
    baseline = aggregate_samples([_clean_sample(wall_clock_ms=100, peak_rss_bytes=1000)])
    faster = aggregate_samples([_clean_sample(wall_clock_ms=94, peak_rss_bytes=1000)])
    leaner = aggregate_samples([_clean_sample(wall_clock_ms=101, peak_rss_bytes=890)])

    assert optimization_gate(baseline, faster)["passed"] is True
    assert optimization_gate(baseline, leaner)["passed"] is True
    assert optimization_gate(baseline, aggregate_samples([_clean_sample(wall_clock_ms=103, peak_rss_bytes=1000)]))["passed"] is False


def test_variant_matrix_is_fixed_and_rotated_deterministically() -> None:
    assert [variant["name"] for variant in VARIANT_MATRIX] == [
        "control-20k-w1",
        "current-20k-w2",
        "small-10k-w2",
        "large-40k-w2",
        "large-80k-w2",
        "fast-20k-w2",
    ]
    assert [variant["name"] for variant in rotate_variants(VARIANT_MATRIX, 2)] == [
        "small-10k-w2",
        "large-40k-w2",
        "large-80k-w2",
        "fast-20k-w2",
        "control-20k-w1",
        "current-20k-w2",
    ]


def test_peak_rss_uses_linux_kibibyte_resource_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.benchmark_fraud_detection as benchmark

    monkeypatch.setattr(
        benchmark.resource,
        "getrusage",
        lambda _kind: type("Usage", (), {"ru_maxrss": 7})(),
    )
    monkeypatch.setattr(benchmark.sys, "platform", "linux")

    assert peak_rss_bytes() == 7 * 1024


def test_runtime_sql_builders_and_copy_generator_are_shared_and_lazy() -> None:
    stage_sql = build_partner_transaction_stage_sql()
    classify_sql = build_partner_transaction_classify_sql()

    assert "CREATE TEMP TABLE partner_transaction_stage" in stage_sql
    assert "ON COMMIT DROP" in stage_sql
    assert "INSERT INTO partner_transaction" in classify_sql
    assert "ON CONFLICT (identify, ingestion_key) DO NOTHING" in classify_sql
    assert "ORDER BY incoming_ordinal" in classify_sql

def test_explain_summary_identifies_slowest_node_and_buffer_classes() -> None:
    summary = summarize_explain_plan(
        {
            "Planning Time": 1.5,
            "Execution Time": 20.0,
            "Plan": {
                "Node Type": "ModifyTable",
                "Actual Total Time": 20.0,
                "Actual Loops": 1,
                "Shared Read Blocks": 2,
                "Plans": [
                    {
                        "Node Type": "Sort",
                        "Actual Total Time": 3.0,
                        "Actual Loops": 1,
                        "Temp Read Blocks": 4,
                    }
                ],
            },
        }
    )

    assert summary["planning_time_ms"] == 1.5
    assert summary["buffer_totals"]["shared_read_blocks"] == 2
    assert summary["buffer_totals"]["temp_read_blocks"] == 4
    assert summary["operation_nodes"]["sort"][0]["node_type"] == "Sort"
    assert summary["slowest_operation"]["node_type"] == "ModifyTable"


@pytest.mark.asyncio
async def test_postgres_preflight_reports_active_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.benchmark_fraud_detection as benchmark

    async def active_writes() -> list[dict[str, Any]]:
        return [{"pid": 11292, "age_seconds": 7200, "command": "INSERT"}]

    monkeypatch.setattr(benchmark, "_find_active_postgres_writes", active_writes)
    report: dict[str, Any] = {"status": "completed", "postgresql": {}}

    assert await _ensure_postgres_quiet(report) is False
    assert report["status"] == "blocked_by_environment"
    assert "pid=11292" in report["error"]
