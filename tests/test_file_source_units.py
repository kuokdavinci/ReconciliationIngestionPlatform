"""TDD contracts for sequential FileDrop/SFTP source-unit discovery."""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from src.fetchers.filedrop_fetcher import FileDropFetcher
from src.fetchers.sftp_fetcher import SFTPFetcher
from src.fetchers.base import BaseFetcher
from src.models.fetch_config import FileDropConfig, SFTPConfig


def test_relative_local_paths_are_resolved_from_application_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert BaseFetcher.resolve_local_path("./mock_data") == (
        Path(__file__).resolve().parents[1] / "mock_data"
    )


@pytest.mark.asyncio
async def test_filedrop_discovers_ready_files_deterministically_with_stable_fingerprints(
    tmp_path,
):
    (tmp_path / "b.xlsx").write_text("B")
    (tmp_path / "a.xlsx").write_text("A")
    config = FileDropConfig(directory=str(tmp_path), pattern="*.xlsx")
    fetcher = FileDropFetcher()

    with patch.object(fetcher, "_is_file_ready", return_value=True):
        first = await fetcher.fetch(config, datetime(2024, 7, 7))
        second = await fetcher.fetch(config, datetime(2024, 7, 7))

    assert [unit["localPath"] for unit in first.units] == [
        str(tmp_path / "a.xlsx"),
        str(tmp_path / "b.xlsx"),
    ]
    assert first.local_path == str(tmp_path / "a.xlsx")
    assert first.metadata["selected_file"] == str(tmp_path / "a.xlsx")
    assert first.units[0]["status"] == "DISCOVERED"
    assert first.units[0]["contentHash"]
    assert [unit["sourceUnitKey"] for unit in first.units] == [
        unit["sourceUnitKey"] for unit in second.units
    ]


@pytest.mark.asyncio
async def test_filedrop_content_change_creates_new_source_unit_key(tmp_path):
    file_path = tmp_path / "settlement.xlsx"
    file_path.write_text("before")
    config = FileDropConfig(directory=str(tmp_path), pattern="*.xlsx")
    fetcher = FileDropFetcher()

    with patch.object(fetcher, "_is_file_ready", return_value=True):
        before = await fetcher.fetch(config, datetime(2024, 7, 7))
        file_path.write_text("after")
        after = await fetcher.fetch(config, datetime(2024, 7, 7))

    assert before.units[0]["sourceUnitKey"] != after.units[0]["sourceUnitKey"]
    assert before.units[0]["contentHash"] != after.units[0]["contentHash"]


@pytest.mark.asyncio
async def test_filedrop_rewrite_with_same_content_keeps_source_unit_key(tmp_path):
    file_path = tmp_path / "settlement.xlsx"
    file_path.write_text("same content")
    config = FileDropConfig(directory=str(tmp_path), pattern="*.xlsx")
    fetcher = FileDropFetcher()

    with patch.object(fetcher, "_is_file_ready", return_value=True):
        first = await fetcher.fetch(config, datetime(2024, 7, 7))
        file_path.touch()
        second = await fetcher.fetch(config, datetime(2024, 7, 7))

    assert first.units[0]["contentHash"] == second.units[0]["contentHash"]
    assert first.units[0]["sourceUnitKey"] == second.units[0]["sourceUnitKey"]


@pytest.mark.asyncio
async def test_filedrop_source_unit_identity_changes_with_config_version(tmp_path):
    file_path = tmp_path / "settlement.xlsx"
    file_path.write_text("same content")
    config = FileDropConfig(directory=str(tmp_path), pattern="*.xlsx")
    fetcher = FileDropFetcher()

    with patch.object(fetcher, "_is_file_ready", return_value=True):
        first = await fetcher.fetch(
            config, datetime(2024, 7, 7), fetch_metadata={"configVersion": "v1"}
        )
        second = await fetcher.fetch(
            config, datetime(2024, 7, 7), fetch_metadata={"configVersion": "v2"}
        )

    assert first.units[0].source_unit_key != second.units[0].source_unit_key


@pytest.mark.asyncio
async def test_filedrop_date_template_scans_only_requested_backfill_day(tmp_path):
    (tmp_path / "settlement_VNPAY_20260809.xlsx").write_text("day 1")
    (tmp_path / "settlement_VNPAY_20260810.xlsx").write_text("day 2")
    config = FileDropConfig(
        directory=str(tmp_path),
        pattern="settlement_VNPAY_{date:%Y%m%d}.xlsx",
    )
    fetcher = FileDropFetcher()

    with patch.object(fetcher, "_is_file_ready", return_value=True):
        result = await fetcher.fetch(config, datetime(2026, 8, 10))

    assert [unit["localPath"] for unit in result.units] == [
        str(tmp_path / "settlement_VNPAY_20260810.xlsx")
    ]


@pytest.mark.asyncio
async def test_sftp_wildcard_downloads_sorted_remote_files_sequentially_with_units(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SFTP_PASS", "secret")
    config = SFTPConfig(
        host="sftp.example.com",
        username="user",
        password="env:SFTP_PASS",
        remote_path="/remote/*.xlsx",
        download_dir=str(tmp_path),
    )
    fetcher = SFTPFetcher()
    download_order = []

    def mock_download(host, port, user, password, remote, local, timeout):
        download_order.append(remote)
        Path(local).write_text(Path(remote).stem)

    with (
        patch.object(
            fetcher,
            "_resolve_remote_paths_via_sftp",
            return_value=["/remote/b.xlsx", "/remote/a.xlsx"],
        ),
        patch.object(fetcher, "_download_via_sftp", side_effect=mock_download),
    ):
        result = await fetcher.fetch(config, datetime(2024, 7, 7))

    assert result.success is True
    assert [unit["sourceIdentity"]["remotePath"] for unit in result.units] == [
        "/remote/a.xlsx",
        "/remote/b.xlsx",
    ]
    assert download_order == ["/remote/a.xlsx", "/remote/b.xlsx"]
    assert len({unit["sourceUnitKey"] for unit in result.units}) == 2
    assert all(unit["status"] == "DISCOVERED" for unit in result.units)


@pytest.mark.asyncio
async def test_sftp_replay_of_same_remote_object_keeps_source_unit_key(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SFTP_PASS", "secret")
    config = SFTPConfig(
        host="sftp.example.com",
        username="user",
        password="env:SFTP_PASS",
        remote_path="/remote/settlement.xlsx",
        download_dir=str(tmp_path),
    )
    fetcher = SFTPFetcher()

    def mock_download(host, port, user, password, remote, local, timeout):
        Path(local).write_text("same remote content")

    with patch.object(fetcher, "_download_via_sftp", side_effect=mock_download):
        first = await fetcher.fetch(config, datetime(2024, 7, 7))
        second = await fetcher.fetch(config, datetime(2024, 7, 7))

    assert first.units[0]["sourceUnitKey"] == second.units[0]["sourceUnitKey"]
