"""Structure signature computation for file format detection.

Computes a fingerprint of a data file's structure (headers, column count,
data type patterns) independent of any MappingConfig. Used by ConfigHealthService
to detect when a partner's file format has changed.
"""

import csv
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class StructureSignature:
    """Fingerprint of a data file's columnar structure.

    Attributes:
        headers: First data row (typically headers/column names).
        column_count: Number of columns in the data.
        sample_rows: Up to 10 sample data rows for AI analysis.
        hash: MD5 of headers + column_count for quick staleness check.
    """

    headers: list[str] = field(default_factory=list)
    column_count: int = 0
    sample_rows: list[list[str]] = field(default_factory=list)
    hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "headers": self.headers,
            "columnCount": self.column_count,
            "sampleRows": self.sample_rows[:5],
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StructureSignature":
        return cls(
            headers=data.get("headers", []),
            column_count=data.get("columnCount", 0),
            sample_rows=data.get("sampleRows", []),
            hash=data.get("hash", ""),
        )


def _normalize_cell(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _compute_hash(headers: list[str], column_count: int) -> str:
    raw = json.dumps([headers, column_count], sort_keys=True, ensure_ascii=False)
    return hashlib.md5(raw.encode()).hexdigest()


def _read_raw_csv(path: Path, max_rows: int = 20) -> list[list[str]]:
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=delimiter)
        rows = []
        for row in reader:
            normalized = [_normalize_cell(c) for c in row]
            if not rows and not any(normalized):
                continue
            if len(rows) >= max_rows:
                break
            rows.append(normalized)
    return rows


def _read_raw_xlsx(path: Path, max_rows: int = 20) -> list[list[str]]:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active
    rows = []
    for row in ws.iter_rows(values_only=True):
        normalized = [_normalize_cell(c) for c in row]
        if not rows and not any(normalized):
            continue
        if len(rows) >= max_rows:
            break
        rows.append(normalized)
    wb.close()
    return rows


def _read_raw_json(path: Path, max_rows: int = 20) -> list[list[str]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    rows: list[list[str]] = []
    if not isinstance(data, list):
        raise ValueError("JSON root must be an array")
    for i, item in enumerate(data):
        if i >= max_rows:
            break
        if isinstance(item, list):
            rows.append([_normalize_cell(c) for c in item])
        elif isinstance(item, dict):
            rows.append([_normalize_cell(v) for v in item.values()])
        else:
            rows.append([_normalize_cell(item)])
    return rows


def read_raw_rows(path: str | Path, max_rows: int = 20) -> list[list[str]]:
    """Read raw rows from any supported data file without needing a MappingConfig.

    Used by compute_signature() and AIConfigGenerator to inspect file structure.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".json":
        return _read_raw_json(p, max_rows)
    if suffix in (".xlsx", ".xlsm"):
        return _read_raw_xlsx(p, max_rows)
    if suffix in (".csv", ".tsv"):
        return _read_raw_csv(p, max_rows)
    raise ValueError(f"Unsupported file extension: {suffix}")


def compute_signature(file_path: str | Path, sample_size: int = 10) -> StructureSignature:
    """Compute a StructureSignature from a data file.

    Process:
    1. Read first (sample_size + 1) raw rows.
    2. Treat first row as headers.
    3. Compute column count and MD5 hash.
    4. Return StructureSignature with up to sample_size data rows.
    """
    raw = read_raw_rows(file_path, max_rows=sample_size + 1)
    if not raw:
        return StructureSignature()

    headers = raw[0] if len(raw) > 0 else []
    sample = raw[1: sample_size + 1] if len(raw) > 1 else []
    column_count = len(headers)

    return StructureSignature(
        headers=headers,
        column_count=column_count,
        sample_rows=sample,
        hash=_compute_hash(headers, column_count),
    )
