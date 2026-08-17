"""Generate a memory-safe overview for a large CSV dataset."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path("data/eda/ibm_aml_li/raw/LI-Small_Trans.csv")
DEFAULT_OUTPUT_DIR = Path("data/eda/ibm_aml_li/profiles")
NULL_TOKENS = {"", "na", "n/a", "none", "null"}
TIMESTAMP_FORMATS = (
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
)
ROLE_BY_NAME = {
    "Timestamp": "datetime",
    "Amount Received": "numeric",
    "Amount Paid": "numeric",
    "Is Laundering": "label",
    "From Account": "identifier",
    "To Account": "identifier",
}


class _DistinctTracker:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._values: set[str] = set()
        self._saturated = False

    def add(self, value: str) -> None:
        if value in self._values:
            return
        if len(self._values) < self._limit:
            self._values.add(value)
        else:
            self._saturated = True

    @property
    def count(self) -> int:
        return len(self._values)

    @property
    def is_exact(self) -> bool:
        return not self._saturated


class _ColumnAccumulator:
    def __init__(
        self,
        name: str,
        source_name: str,
        role: str,
        distinct_limit: int,
    ) -> None:
        self.name = name
        self.source_name = source_name
        self.role = role
        self.null_count = 0
        self.invalid_count = 0
        self.valid_count = 0
        self.samples: list[str] = []
        self.distinct = _DistinctTracker(distinct_limit)
        self.numeric_min: Decimal | None = None
        self.numeric_max: Decimal | None = None
        self.datetime_min: datetime | None = None
        self.datetime_max: datetime | None = None

    def update(self, raw_value: str) -> None:
        value = raw_value.strip()
        if value.lower() in NULL_TOKENS:
            self.null_count += 1
            return

        self.valid_count += 1
        self.distinct.add(value)
        if len(self.samples) < 5 and value not in self.samples:
            self.samples.append(value)

        if self.role == "numeric":
            self._update_numeric(value)
        elif self.role == "datetime":
            self._update_datetime(value)

    def _update_numeric(self, value: str) -> None:
        try:
            number = Decimal(value)
        except InvalidOperation:
            self.invalid_count += 1
            return

        if self.numeric_min is None or number < self.numeric_min:
            self.numeric_min = number
        if self.numeric_max is None or number > self.numeric_max:
            self.numeric_max = number

    def _update_datetime(self, value: str) -> None:
        parsed = None
        for timestamp_format in TIMESTAMP_FORMATS:
            try:
                parsed = datetime.strptime(value, timestamp_format)
                break
            except ValueError:
                continue

        if parsed is None:
            self.invalid_count += 1
            return
        if self.datetime_min is None or parsed < self.datetime_min:
            self.datetime_min = parsed
        if self.datetime_max is None or parsed > self.datetime_max:
            self.datetime_max = parsed

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "source_name": self.source_name,
            "role": self.role,
            "nullable_count": self.null_count,
            "valid_count": self.valid_count,
            "invalid_count": self.invalid_count,
            "distinct_count": self.distinct.count,
            "distinct_count_exact": self.distinct.is_exact,
            "sample_values": self.samples,
        }
        if self.role == "numeric":
            result["numeric"] = {
                "min": _decimal_text(self.numeric_min),
                "max": _decimal_text(self.numeric_max),
            }
        if self.role == "datetime":
            result["datetime"] = {
                "min": _datetime_text(self.datetime_min),
                "max": _datetime_text(self.datetime_max),
            }
        return result


def normalize_headers(raw_headers: list[str]) -> list[str]:
    """Make duplicate source headers explicit for downstream profiling."""

    normalized: list[str] = []
    account_count = 0
    seen: Counter[str] = Counter()

    for index, raw_header in enumerate(raw_headers, start=1):
        header = raw_header.strip() or f"column_{index}"
        if header == "Account":
            account_count += 1
            header = "From Account" if account_count == 1 else "To Account"
        elif seen[header]:
            header = f"{header}_{seen[header] + 1}"
        seen[header] += 1
        normalized.append(header)

    return normalized


def _role_for(name: str) -> str:
    if name in ROLE_BY_NAME:
        return ROLE_BY_NAME[name]
    if name.endswith("Bank") or name.endswith("Currency"):
        return "categorical"
    if name == "Payment Format":
        return "categorical"
    return "unknown"


def _is_blank_row(row: list[str]) -> bool:
    return not row or all(not value.strip() for value in row)


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _datetime_text(value: datetime | None) -> str | None:
    return None if value is None else value.strftime("%Y/%m/%d %H:%M")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_overview(path: Path, *, distinct_limit: int = 10_000) -> dict[str, Any]:
    """Build a bounded-memory overview without materializing the CSV."""

    if not path.is_file():
        raise FileNotFoundError(f"Dataset file not found: {path}")
    if distinct_limit < 1:
        raise ValueError("distinct_limit must be positive")

    csv.field_size_limit(sys.maxsize)
    row_count = 0
    valid_row_count = 0
    blank_row_count = 0
    malformed_row_count = 0
    label_distributions: dict[str, Counter[str]] = {}

    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source)
        try:
            raw_headers = next(reader)
        except StopIteration as exc:
            raise ValueError("Dataset file is empty") from exc

        headers = normalize_headers(raw_headers)
        accumulators = [
            _ColumnAccumulator(
                name=name,
                source_name=raw_headers[index],
                role=_role_for(name),
                distinct_limit=distinct_limit,
            )
            for index, name in enumerate(headers)
        ]

        for row in reader:
            if _is_blank_row(row):
                blank_row_count += 1
                continue

            row_count += 1
            if len(row) != len(headers):
                malformed_row_count += 1
                continue

            valid_row_count += 1
            for accumulator, value in zip(accumulators, row):
                accumulator.update(value)
                if accumulator.role == "label" and value.strip().lower() not in NULL_TOKENS:
                    label_distributions.setdefault(accumulator.name, Counter())[value.strip()] += 1

    columns = [accumulator.as_dict() for accumulator in accumulators]
    timestamp_column = next(
        (column for column in columns if column["role"] == "datetime"),
        None,
    )

    return {
        "file": {
            "name": path.name,
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "encoding": "utf-8",
            "delimiter": ",",
            "row_count": row_count,
            "valid_row_count": valid_row_count,
        },
        "schema": {
            "column_count": len(headers),
            "columns": columns,
        },
        "quality": {
            "blank_row_count": blank_row_count,
            "malformed_row_count": malformed_row_count,
            "null_cell_count": sum(column["nullable_count"] for column in columns),
        },
        "observations": {
            "timestamp_range": (
                timestamp_column.get("datetime", {})
                if timestamp_column is not None
                else {"min": None, "max": None}
            ),
            "label_distribution": {
                name: dict(counts) for name, counts in label_distributions.items()
            },
        },
    }


def render_markdown(overview: dict[str, Any]) -> str:
    """Render the JSON overview as a concise human-readable report."""

    file_info = overview["file"]
    schema = overview["schema"]
    quality = overview["quality"]
    observations = overview["observations"]
    lines = [
        "# Dataset Overview",
        "",
        f"- File: {file_info['name']}",
        f"- Rows: {file_info['row_count']:,} "
        f"(valid: {file_info['valid_row_count']:,})",
        f"- Columns: {schema['column_count']}",
        f"- Size: {file_info['size_bytes']:,} bytes",
        f"- SHA-256: {file_info['sha256']}",
        "",
        "## Schema",
        "",
        "| Column | Source header | Role | Nulls | Distinct | Exact | Samples |",
        "|---|---|---:|---:|---:|:---:|---|",
    ]

    for column in schema["columns"]:
        samples = ", ".join(column["sample_values"])
        lines.append(
            f"| {column['name']} | {column['source_name']} | "
            f"{column['role']} | {column['nullable_count']:,} | "
            f"{column['distinct_count']:,} | "
            f"{'yes' if column['distinct_count_exact'] else 'no'} | {samples} |"
        )

    lines.extend(
        [
            "",
            "## Quality Summary",
            "",
            f"- Blank rows: {quality['blank_row_count']:,}",
            f"- Malformed rows: {quality['malformed_row_count']:,}",
            f"- Null cells: {quality['null_cell_count']:,}",
            "",
            "## Observations",
            "",
            f"- Timestamp range: {observations['timestamp_range']['min']} → "
            f"{observations['timestamp_range']['max']}",
        ]
    )

    for name, distribution in observations["label_distribution"].items():
        lines.append(
            f"- {name} distribution: {json.dumps(distribution, ensure_ascii=False)}"
        )

    numeric_columns = [
        column for column in schema["columns"] if column["role"] == "numeric"
    ]
    if numeric_columns:
        lines.extend(
            [
                "",
                "## Numeric Summary",
                "",
                "| Column | Min | Max | Invalid |",
                "|---|---:|---:|---:|",
            ]
        )
        for column in numeric_columns:
            numeric = column["numeric"]
            lines.append(
                f"| {column['name']} | {numeric['min']} | {numeric['max']} | "
                f"{column['invalid_count']:,} |"
            )

    return "\n".join(lines) + "\n"


def write_overview(
    input_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    distinct_limit: int = 10_000,
) -> tuple[Path, Path]:
    """Write JSON and Markdown overview files and return their paths."""

    overview = build_overview(input_path, distinct_limit=distinct_limit)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "dataset_overview.json"
    markdown_path = output_dir / "dataset_overview.md"
    json_path.write_text(
        json.dumps(overview, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(overview), encoding="utf-8")
    return json_path, markdown_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a bounded-memory overview for a large CSV dataset."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--distinct-limit", type=int, default=10_000)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    json_path, markdown_path = write_overview(
        args.input,
        args.output_dir,
        distinct_limit=args.distinct_limit,
    )
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
