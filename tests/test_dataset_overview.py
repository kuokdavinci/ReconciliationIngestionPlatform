"""Tests for the streaming dataset overview generator."""

import json
from pathlib import Path

from scripts.eda.dataset_overview import build_overview, write_overview


HEADER = (
    "Timestamp,From Bank,Account,To Bank,Account,Amount Received,"
    "Receiving Currency,Amount Paid,Payment Currency,Payment Format,Is Laundering"
)


def _write_fixture(path: Path, *rows: str) -> None:
    path.write_text("\n".join((HEADER, *rows)) + "\n", encoding="utf-8")


def test_build_overview_normalizes_duplicate_account_headers_and_streams_stats(
    tmp_path: Path,
) -> None:
    source = tmp_path / "LI-Small_Trans.csv"
    _write_fixture(
        source,
        "2022/09/01 00:08,011,FROM-1,011,TO-1,3195403.00,US Dollar,3195403.00,US Dollar,Reinvestment,0",
        "2022/09/01 00:21,03402,FROM-2,03402,TO-2,1858.96,US Dollar,1858.96,US Dollar,Cheque,1",
        "2022/09/02 00:00,011,FROM-3,001120,TO-3,12.32,US Dollar,12.32,US Dollar,Cheque,0",
    )

    overview = build_overview(source, distinct_limit=2)

    assert overview["file"]["row_count"] == 3
    assert overview["file"]["valid_row_count"] == 3
    assert [column["name"] for column in overview["schema"]["columns"]] == [
        "Timestamp",
        "From Bank",
        "From Account",
        "To Bank",
        "To Account",
        "Amount Received",
        "Receiving Currency",
        "Amount Paid",
        "Payment Currency",
        "Payment Format",
        "Is Laundering",
    ]

    columns = {column["name"]: column for column in overview["schema"]["columns"]}
    assert columns["Amount Received"]["role"] == "numeric"
    assert columns["Amount Received"]["numeric"]["min"] == "12.32"
    assert columns["Amount Received"]["numeric"]["max"] == "3195403.00"
    assert columns["From Account"]["distinct_count_exact"] is False
    assert columns["From Account"]["distinct_count"] == 2
    assert overview["observations"]["timestamp_range"] == {
        "min": "2022/09/01 00:08",
        "max": "2022/09/02 00:00",
    }
    assert overview["observations"]["label_distribution"]["Is Laundering"] == {
        "0": 2,
        "1": 1,
    }


def test_build_overview_counts_malformed_rows_without_crashing(tmp_path: Path) -> None:
    source = tmp_path / "malformed.csv"
    _write_fixture(
        source,
        "2022/09/01 00:08,011,FROM-1,011,TO-1,10.00,US Dollar,10.00,US Dollar,Cheque,0",
        "2022/09/01 00:21,03402,FROM-2,03402,TO-2,20.00,US Dollar,20.00,US Dollar,Cheque",
    )

    overview = build_overview(source)

    assert overview["file"]["row_count"] == 2
    assert overview["file"]["valid_row_count"] == 1
    assert overview["quality"]["malformed_row_count"] == 1


def test_write_overview_creates_machine_and_human_readable_outputs(tmp_path: Path) -> None:
    source = tmp_path / "sample.csv"
    _write_fixture(
        source,
        "2022/09/01 00:08,011,FROM-1,011,TO-1,10.00,US Dollar,10.00,US Dollar,Cheque,0",
    )

    json_path, markdown_path = write_overview(source, tmp_path / "profiles")

    assert json_path.name == "dataset_overview.json"
    assert markdown_path.name == "dataset_overview.md"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["file"]["name"] == "sample.csv"
    assert "## Schema" in markdown_path.read_text(encoding="utf-8")
