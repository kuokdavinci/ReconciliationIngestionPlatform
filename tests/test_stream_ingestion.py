from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application.ingestion.contracts import ProcessFileCommand
from src.application.automation.stream_ingestion import (
    cleanup_source_unit,
    failed_ingestion_result,
    run_ingestion,
)
from src.domain.fetch_config.models import FetchConfig, FetchMethod, FileDropConfig
from src.domain.ingestion.source_units import SourceUnitMetadata


@pytest.mark.asyncio
async def test_run_ingestion_uses_the_public_process_file_command():
    result = SimpleNamespace(
        file_record=SimpleNamespace(processing_status="COMPLETED"),
        stats=SimpleNamespace(total_rows=0, success_rows=0, failed_rows=0),
    )
    pipeline = MagicMock()
    pipeline.execute = AsyncMock(return_value=result)

    with patch(
        "src.application.automation.stream_ingestion.build_ingestion_pipeline",
        return_value=pipeline,
    ) as build:
        output = await run_ingestion(
            db=MagicMock(),
            config_loader=MagicMock(),
            file_path="/tmp/page-1.json",
            partner="VIETTELPAY",
            reconciliation_date=datetime(2026, 8, 13, tzinfo=UTC),
            batch_size=100,
            fetch_unit_metadata={"sourceUnitKey": "page-1"},
            config_version="v1",
            backfill_run_id="backfill-001",
            enable_config_health_check=True,
            validate_rows=True,
        )

    assert output is result
    assert build.call_args.kwargs["fast_mode"] is False
    command = pipeline.execute.await_args.args[0]
    assert isinstance(command, ProcessFileCommand)
    assert command.file_path == "/tmp/page-1.json"
    assert command.partner == "VIETTELPAY"
    assert command.fetch_unit_metadata == {"sourceUnitKey": "page-1"}
    assert command.config_version == "v1"
    assert command.backfill_run_id == "backfill-001"
    assert command.enable_config_health_check is True


def test_file_read_failure_is_terminal_and_not_source_persist_error():
    result = SimpleNamespace(
        file_record=SimpleNamespace(stage_summary={"currentStage": "READING"}),
        errors=[{"field": "ingestion_error", "reason": "Invalid XLSX archive"}],
    )

    failure = failed_ingestion_result(result)

    assert failure["errorCode"] == "file_parse_error"
    assert failure["retryable"] is False
    assert failure["error"] == "Invalid XLSX archive"


def test_persistence_failure_keeps_source_persist_error_retryability():
    result = SimpleNamespace(
        file_record=SimpleNamespace(stage_summary={"currentStage": "PERSISTING"}),
        errors=[{"field": "ingestion_error", "reason": "Database write failed"}],
    )

    failure = failed_ingestion_result(result)

    assert failure["errorCode"] == "source_persist_error"
    assert failure["retryable"] is True


def test_missing_ingestion_identity_is_terminal():
    result = SimpleNamespace(
        file_record=SimpleNamespace(stage_summary={"currentStage": "FINALIZING"}),
        stats=SimpleNamespace(total_rows=2, success_rows=0, failed_rows=2),
        errors=[
            {"field": "id", "reason": "source field value is None"},
            {"field": "trace", "reason": "source field value is None"},
        ],
    )

    failure = failed_ingestion_result(result)

    assert failure["errorCode"] == "ingestion_key_error"
    assert failure["retryable"] is False
    assert "both id and trace are missing" in failure["error"]


@pytest.mark.asyncio
async def test_cleanup_source_unit_archives_only_after_checkpoint_completion(tmp_path):
    source_path = tmp_path / "settlement.xlsx"
    archive_dir = tmp_path / "archive"
    source_path.write_text("payload")
    config = FetchConfig(
        partner="VNPAY",
        fetch_method=FetchMethod.FILEDROP,
        archive_dir=str(archive_dir),
        cleanup_after_ingest=True,
        filedrop=FileDropConfig(directory=str(tmp_path)),
    )

    await cleanup_source_unit(
        config,
        SourceUnitMetadata(localPath=str(source_path), sourceUnitKey="unit-1"),
    )

    assert not source_path.exists()
    assert (archive_dir / source_path.name).read_text() == "payload"


@pytest.mark.asyncio
async def test_cleanup_source_unit_preserves_source_when_cleanup_is_disabled(tmp_path):
    source_path = tmp_path / "settlement.xlsx"
    source_path.write_text("payload")
    config = FetchConfig(
        partner="VNPAY",
        fetch_method=FetchMethod.FILEDROP,
        cleanup_after_ingest=False,
        filedrop=FileDropConfig(directory=str(tmp_path)),
    )

    await cleanup_source_unit(
        config,
        SourceUnitMetadata(localPath=str(source_path), sourceUnitKey="unit-1"),
    )

    assert source_path.read_text() == "payload"
