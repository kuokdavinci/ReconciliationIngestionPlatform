from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Self, Any

from src.domain.mapping.models import MappingConfig

VALID_EXTENSIONS = {".json"}


class JSONStreamReader:
    def __init__(
        self,
        file_path: str | Path,
        *,
        start_row: int = 1,
        skip_empty_rows: bool = True,
        encoding: str = "utf-8",
    ) -> None:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if path.suffix.lower() not in VALID_EXTENSIONS:
            raise ValueError(
                f"Unsupported file extension '{path.suffix}'. "
                f"Must be one of: {', '.join(sorted(VALID_EXTENSIONS))}"
            )

        self._file_path: Path = path
        self._start_row = start_row
        self._skip_empty_rows = skip_empty_rows
        self._encoding = encoding
        self._rows: list[Any] | None = None

    @classmethod
    def from_mapping_config(
        cls, file_path: str | Path, config: MappingConfig
    ) -> JSONStreamReader:
        return cls(
            file_path=file_path,
            start_row=config.start_row,
            skip_empty_rows=True,
        )

    def __enter__(self) -> Self:
        with open(self._file_path, mode="r", encoding=self._encoding) as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(
                f"JSON root must be an array, got {type(data).__name__}"
            )
        self._rows = data
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self._rows = None
        return False

    @staticmethod
    def _is_empty_row(row: Any) -> bool:
        if isinstance(row, (list, tuple)):
            return all(cell is None or cell == "" for cell in row)
        if isinstance(row, dict):
            return all(v is None or v == "" for v in row.values())
        return row is None

    @staticmethod
    def _sanitize_cell(value: Any) -> Any:
        if isinstance(value, float):
            return str(value)
        return value

    def iter_rows(self) -> Iterator[Any]:
        if self._rows is None:
            raise RuntimeError("Reader must be used as context manager")

        for row_number, row in enumerate(self._rows, start=1):
            if row_number < self._start_row:
                continue

            if self._skip_empty_rows and self._is_empty_row(row):
                continue

            if isinstance(row, dict):
                yield {k: self._sanitize_cell(v) for k, v in row.items()}
            elif isinstance(row, list):
                yield tuple(self._sanitize_cell(v) for v in row)
            else:
                yield (self._sanitize_cell(row),)
