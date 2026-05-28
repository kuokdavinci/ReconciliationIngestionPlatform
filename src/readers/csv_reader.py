"""CSV streaming reader using Python's standard csv module."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path
from typing import Self, TextIO

from src.models.mapping_config import MappingConfig

VALID_EXTENSIONS = {".csv"}


class CSVStreamReader:
    """Memory-efficient CSV file reader with ExcelStreamReader-compatible output."""

    DEFAULT_SKIP_PATTERNS: list[str] = [
        "total",
        "grand total",
        "summary",
        "footer",
        "合计",
        "总计",
        "小计",
    ]

    def __init__(
        self,
        file_path: str | Path,
        *,
        start_row: int = 1,
        skip_empty_rows: bool = True,
        skip_patterns: list[str] | None = None,
        delimiter: str = ",",
        encoding: str = "utf-8",
    ) -> None:
        """Initialize the reader with a CSV file path."""
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
        self._skip_patterns = (
            skip_patterns if skip_patterns is not None
            else self.DEFAULT_SKIP_PATTERNS
        )
        self._delimiter = delimiter
        self._encoding = encoding
        self._file: TextIO | None = None

    @classmethod
    def from_mapping_config(
        cls, file_path: str | Path, config: MappingConfig
    ) -> CSVStreamReader:
        """Create a CSVStreamReader from a MappingConfig object."""
        return cls(
            file_path=file_path,
            start_row=config.start_row,
            skip_empty_rows=True,
        )

    def __enter__(self) -> Self:
        """Open the CSV file and return self."""
        self._file = open(
            self._file_path,
            mode="r",
            newline="",
            encoding=self._encoding,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Close the CSV file, even if an exception occurred."""
        if self._file is not None:
            self._file.close()
            self._file = None
        return False

    def _require_file(self) -> TextIO:
        """Return the open file handle or raise if used outside a context manager."""
        if self._file is None:
            raise RuntimeError("Reader must be used as context manager")
        return self._file

    @staticmethod
    def _is_empty_row(row: tuple[str, ...]) -> bool:
        """Check if a row is empty."""
        return all(cell is None or cell == "" for cell in row)

    def _should_skip_row(self, row: tuple[str, ...]) -> bool:
        """Determine whether a row should be skipped."""
        if self._skip_empty_rows and self._is_empty_row(row):
            return True

        if self._skip_patterns:
            for cell in row:
                cell_str = str(cell).lower()
                for pattern in self._skip_patterns:
                    if pattern.lower() in cell_str:
                        return True

        return False

    def iter_rows(self) -> Iterator[tuple[str, ...]]:
        """Iterate over CSV rows starting from start_row."""
        file_obj = self._require_file()
        reader = csv.reader(file_obj, delimiter=self._delimiter)
        for row_number, row in enumerate(reader, start=1):
            if row_number < self._start_row:
                continue

            row_tuple = tuple(row)
            if self._should_skip_row(row_tuple):
                continue

            yield row_tuple
