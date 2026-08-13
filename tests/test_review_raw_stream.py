from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.domain.review.models import ReviewPacket
from src.services.review_raw_stream import (
    read_review_stream_page,
    resolve_review_source_file,
)


def _packet(stage_key: str = "stream-a") -> ReviewPacket:
    return ReviewPacket(
        _id="packet-1",
        sourceType="SCHEDULER_JOB",
        partner="VIETTELPAY",
        fileName="settlement.json",
        fileTypeDetected="SETTLEMENT",
        rawStageKey=stage_key,
        structureSignature={"firstDataRowIndex": 1},
    )


def _file_packet(source_file_path: str) -> ReviewPacket:
    return ReviewPacket(
        _id="packet-file-1",
        sourceType="SCHEDULER_JOB",
        partner="MOMO",
        fileName="settlement.csv",
        fileTypeDetected="SETTLEMENT",
        sourceFilePath=source_file_path,
        structureSignature={"firstDataRowIndex": 1},
    )


@pytest.mark.asyncio
async def test_reads_ordered_rows_across_pages_with_global_pagination(tmp_path: Path):
    first = tmp_path / "page-1.json"
    first.write_text('{"items":[{"id":"VTP-001"},{"id":"VTP-002"}]}')
    second = tmp_path / "page-2.json"
    second.write_text('{"items":[{"id":"VTP-003"},{"id":"VTP-004"}]}')

    pages = [
        SimpleNamespace(page=1, source_unit_key="unit-1", local_path=str(first)),
        SimpleNamespace(page=2, source_unit_key="unit-2", local_path=str(second)),
    ]
    raw_repo = SimpleNamespace(
        find_for_replay=AsyncMock(return_value=pages),
        materialize=AsyncMock(side_effect=lambda page, _destination: page.local_path),
    )

    with patch("src.services.review_raw_stream.RawIngestionPageRepository", return_value=raw_repo):
        result = await read_review_stream_page(
            db=object(), packet=_packet(), offset=1, limit=2
        )

    assert result["totalRecords"] == 4
    assert result["pageCount"] == 2
    assert result["hasMore"] is True
    assert [row["values"]["id"] for row in result["rows"]] == ["VTP-002", "VTP-003"]
    assert [row["sourceUnitKey"] for row in result["rows"]] == ["unit-1", "unit-2"]
    assert [row["streamRowIndex"] for row in result["rows"]] == [2, 3]


@pytest.mark.asyncio
async def test_stream_reader_never_reads_pages_from_another_stage(tmp_path: Path):
    page_path = tmp_path / "page.json"
    page_path.write_text('{"items":[{"id":"VTP-OTHER"}]}')
    page = SimpleNamespace(page=1, source_unit_key="other-unit", local_path=str(page_path))
    raw_repo = SimpleNamespace(
        find_for_replay=AsyncMock(return_value=[page]),
        materialize=AsyncMock(return_value=str(page_path)),
    )

    with patch("src.services.review_raw_stream.RawIngestionPageRepository", return_value=raw_repo):
        await read_review_stream_page(
            db=object(), packet=_packet("stream-a"), offset=0, limit=50
        )

    raw_repo.find_for_replay.assert_awaited_once_with("stream-a")


@pytest.mark.asyncio
async def test_stream_reader_rejects_packet_without_stream_scope():
    packet = _packet()
    packet.raw_stage_key = None

    with pytest.raises(ValueError, match="rawStageKey"):
        await read_review_stream_page(db=object(), packet=packet, offset=0, limit=50)


@pytest.mark.asyncio
async def test_reads_file_scoped_rows_when_packet_has_no_raw_stage(tmp_path: Path):
    source = tmp_path / "settlement.csv"
    source.write_text("MOMO-001,100\nMOMO-002,200\nMOMO-003,300\n")

    result = await read_review_stream_page(
        db=object(),
        packet=_file_packet(str(source)),
        offset=1,
        limit=1,
    )

    assert result["rawStageKey"] is None
    assert result["totalRecords"] == 3
    assert result["pageCount"] == 1
    assert result["rows"][0]["values"] == ("MOMO-002", "200")
    assert result["rows"][0]["sourceUnitKey"] == "settlement.csv"


@pytest.mark.asyncio
async def test_file_reader_uses_parse_strategy_when_structure_signature_is_missing(tmp_path: Path):
    source = tmp_path / "settlement.csv"
    source.write_text("id,amount\nMOMO-001,100\nMOMO-002,200\n")
    packet = ReviewPacket(
        _id="packet-file-2",
        sourceType="SCHEDULER_JOB",
        partner="MOMO",
        fileName="settlement.csv",
        fileTypeDetected="SETTLEMENT",
        sourceFilePath=str(source),
        parseStrategy={"startRow": 2},
    )

    result = await read_review_stream_page(db=object(), packet=packet, offset=0, limit=50)

    assert result["totalRecords"] == 2
    assert [row["values"] for row in result["rows"]] == [
        ("MOMO-001", "100"),
        ("MOMO-002", "200"),
    ]


def test_resolves_airflow_source_path_inside_api_container(tmp_path: Path):
    source = tmp_path / "settlement.xlsx"
    source.write_bytes(b"fixture")
    packet = _file_packet(f"/opt/airflow/app{source}")

    with patch(
        "src.services.review_raw_stream._candidate_source_paths",
        return_value=[Path("/missing/source.xlsx"), source],
    ):
        assert resolve_review_source_file(packet) == source


@pytest.mark.asyncio
async def test_rejects_file_packet_with_metadata_only_raw_stage(tmp_path: Path):
    source = tmp_path / "settlement.csv"
    source.write_text("MOMO-001,100\n")
    packet = _file_packet(str(source))
    packet.raw_stage_key = "invalid-file-stage"
    raw_repo = SimpleNamespace(find_for_replay=AsyncMock(return_value=[]))

    with patch("src.services.review_raw_stream.RawIngestionPageRepository", return_value=raw_repo):
        with pytest.raises(ValueError, match="file-level packets must omit rawStageKey"):
            await read_review_stream_page(
                db=object(), packet=packet, offset=0, limit=50
            )
