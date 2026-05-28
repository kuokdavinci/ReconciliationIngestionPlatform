"""Streaming reader package."""

from pathlib import Path

from src.models.mapping_config import MappingConfig
from src.readers.csv_reader import CSVStreamReader
from src.readers.excel_reader import ExcelStreamReader


def create_reader(
    file_path: str | Path,
    config: MappingConfig,
) -> CSVStreamReader | ExcelStreamReader:
    """Create the appropriate stream reader based on file extension."""
    suffix = Path(file_path).suffix.lower()
    if suffix == ".csv":
        return CSVStreamReader.from_mapping_config(file_path, config)
    if suffix in {".xlsx", ".xlsm"}:
        return ExcelStreamReader.from_mapping_config(file_path, config)
    raise ValueError(
        f"Unsupported file extension '{suffix}'. "
        "Must be one of: .csv, .xlsm, .xlsx"
    )


__all__ = ["CSVStreamReader", "ExcelStreamReader", "create_reader"]
