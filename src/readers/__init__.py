"""Streaming reader package."""

from pathlib import Path

from src.models.mapping_config import MappingConfig
from src.readers.csv_reader import CSVStreamReader
from src.readers.excel_reader import ExcelStreamReader
from src.readers.json_reader import JSONStreamReader


def create_reader(
    file_path: str | Path,
    config: MappingConfig,
) -> CSVStreamReader | ExcelStreamReader | JSONStreamReader:
    """Create the appropriate stream reader based on file extension."""
    suffix = Path(file_path).suffix.lower()
    if suffix in {".csv", ".tsv"}:
        return CSVStreamReader.from_mapping_config(file_path, config)
    if suffix in {".xlsx", ".xlsm"}:
        return ExcelStreamReader.from_mapping_config(file_path, config)
    if suffix == ".json":
        return JSONStreamReader.from_mapping_config(file_path, config)
    raise ValueError(
        f"Unsupported file extension '{suffix}'. "
        "Must be one of: .csv, .tsv, .xlsx, .xlsm, .json"
    )


__all__ = ["CSVStreamReader", "ExcelStreamReader", "JSONStreamReader", "create_reader"]
