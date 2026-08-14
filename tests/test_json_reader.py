"""Test suite for JSONStreamReader."""

import json
import tempfile
from pathlib import Path

import pytest

from src.core.enums import FileType
from src.domain.mapping.models import MappingConfig
from src.readers import create_reader
from src.readers.json_reader import JSONStreamReader


def _temp_path(suffix: str) -> Path:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        return Path(f.name)


def _mapping_config() -> MappingConfig:
    return MappingConfig(
        partner="test",
        workflowType="recon",
        fileType=FileType.SETTLEMENT,
        sheetName="Sheet1",
        startRow=1,
        fieldMappings=[],
    )


class TestJSONStreamReaderInit:
    def test_file_not_found_raises(self) -> None:
        missing = _temp_path(".json")
        missing.unlink()
        with pytest.raises(FileNotFoundError, match="File not found"):
            JSONStreamReader(missing)

    def test_non_json_extension_raises(self) -> None:
        txt = _temp_path(".txt")
        txt.write_text("[]")
        with pytest.raises(ValueError, match="Unsupported file extension"):
            JSONStreamReader(txt)
        txt.unlink(missing_ok=True)

    def test_root_must_be_array_or_items_envelope(self, tmp_path: Path) -> None:
        path = tmp_path / "obj.json"
        with open(path, "w") as f:
            json.dump({"key": "val"}, f)
        with pytest.raises(ValueError, match="array or an object"):
            with JSONStreamReader(path):
                pass


class TestJSONRowIteration:
    def test_array_of_arrays(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        data = [["A", 1], ["B", 2]]
        with open(path, "w") as f:
            json.dump(data, f)
        with JSONStreamReader(path) as reader:
            rows = list(reader.iter_rows())
        assert rows == [("A", 1), ("B", 2)]

    def test_start_row_offset(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        data = [["id", "amount"], ["TXN001", 100], ["TXN002", 200]]
        with open(path, "w") as f:
            json.dump(data, f)
        with JSONStreamReader(path, start_row=2) as reader:
            rows = list(reader.iter_rows())
        assert rows == [("TXN001", 100), ("TXN002", 200)]

    def test_array_of_objects(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        data = [{"id": "A", "val": 1}, {"id": "B", "val": 2}]
        with open(path, "w") as f:
            json.dump(data, f)
        with JSONStreamReader(path) as reader:
            rows = list(reader.iter_rows())
        assert rows == [{"id": "A", "val": 1}, {"id": "B", "val": 2}]

    def test_pagination_envelope_iterates_items(self, tmp_path: Path) -> None:
        path = tmp_path / "page.json"
        data = {
            "page": 2,
            "cursorBefore": "cursor-1",
            "nextCursor": "cursor-2",
            "items": [{"id": "VTP-003", "amount": "300000"}],
        }
        with open(path, "w") as f:
            json.dump(data, f)
        with JSONStreamReader(path) as reader:
            rows = list(reader.iter_rows())
        assert rows == [{"id": "VTP-003", "amount": "300000"}]

    def test_empty_rows_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        data = [["A", 1], [], ["B", 2], {}]
        with open(path, "w") as f:
            json.dump(data, f)
        with JSONStreamReader(path) as reader:
            rows = list(reader.iter_rows())
        assert rows == [("A", 1), ("B", 2)]

    def test_floats_converted_to_strings(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        data = [["TXN001", 100500.0], ["TXN002", 200.75]]
        with open(path, "w") as f:
            json.dump(data, f)
        with JSONStreamReader(path) as reader:
            rows = list(reader.iter_rows())
        assert rows == [("TXN001", "100500.0"), ("TXN002", "200.75")]

    def test_iter_rows_outside_context_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        with open(path, "w") as f:
            json.dump([["A"]], f)
        reader = JSONStreamReader(path)
        with pytest.raises(RuntimeError, match="context manager"):
            list(reader.iter_rows())


class TestJSONMappingConfigIntegration:
    def test_from_mapping_config_returns_reader(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        with open(path, "w") as f:
            json.dump([], f)
        reader = JSONStreamReader.from_mapping_config(path, _mapping_config())
        assert isinstance(reader, JSONStreamReader)

    def test_from_mapping_config_uses_start_row(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        with open(path, "w") as f:
            json.dump([], f)
        config = _mapping_config()
        config.start_row = 2
        reader = JSONStreamReader.from_mapping_config(path, config)
        assert reader._start_row == 2


class TestCreateReaderJSON:
    def test_json_extension_returns_json_reader(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        with open(path, "w") as f:
            json.dump([], f)
        reader = create_reader(path, _mapping_config())
        assert isinstance(reader, JSONStreamReader)
