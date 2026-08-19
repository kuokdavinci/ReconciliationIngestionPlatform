"""Unit tests for the Sprint 3 fraud-dataset benchmark helpers."""

from pathlib import Path

from scripts.benchmark_fraud_detection import (
    BENCHMARK_WORKFLOW,
    build_mapping_document,
    build_benchmark_config,
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
    assert mappings["extra.sourceTimestamp"]["column"] == 2
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
    import pytest

    with pytest.raises(ValueError, match="batch_size"):
        build_benchmark_config(batch_size=0, write_workers=2, full_only=True)
    with pytest.raises(ValueError, match="write_workers"):
        build_benchmark_config(batch_size=100_000, write_workers=0, full_only=True)
