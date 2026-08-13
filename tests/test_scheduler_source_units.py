from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.core.enums import ProcessingStatus
from src.fetchers.base import FetchResult
from src.domain.fetch_config.models import (
    APIConfig,
    APIPaginationConfig,
    FetchConfig,
    FetchMethod,
    FileDropConfig,
)
from src.domain.ingestion.checkpoints import (
    CheckpointStatus,
    IngestionCheckpoint,
    IngestionMode,
)
from src.scheduler.jobs import (
    _failed_ingestion_result,
    _current_business_day_start,
    _run_ingestion,
    _stream_identity,
    _units_after_checkpoint,
    run_fetch_config_once,
)


def test_current_business_day_start_uses_configured_timezone_boundary():
    value = datetime(2026, 8, 10, 17, 30, tzinfo=UTC)

    result = _current_business_day_start(value)

    assert result.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat() == "2026-08-11"
    assert result.hour == 0
    assert result.minute == 0


class _SequentialCheckpointRepository:
    def __init__(self):
        self.checkpoint = None

    async def find_by_stream(self, **kwargs):
        return self.checkpoint

    async def claim_unit(self, **kwargs):
        if self.checkpoint is None:
            self.checkpoint = IngestionCheckpoint(
                partner=kwargs["partner"],
                fetch_config_id=kwargs["fetch_config_id"],
                source_type=kwargs["source_type"],
                stream_key=kwargs["stream_key"],
            )
        self.checkpoint.current_unit_key = kwargs["unit_key"]
        self.checkpoint.cursor_before = kwargs["cursor_before"]
        self.checkpoint.claim_id = f"claim-{kwargs['unit_key']}"
        self.checkpoint.attempt_count += 1
        self.checkpoint.status = CheckpointStatus.PROCESSING
        self.checkpoint.stream_metadata = kwargs["stream_metadata"]
        return self.checkpoint, True

    async def mark_completed(self, checkpoint, **kwargs):
        checkpoint.last_completed_unit_key = kwargs["unit_key"]
        checkpoint.cursor_after = kwargs["cursor_after"]
        checkpoint.high_water_mark = kwargs["high_water_mark"]
        checkpoint.stream_ended = (kwargs["high_water_mark"] or {}).get("hasMore") is False
        checkpoint.status = CheckpointStatus.COMPLETED
        return True

    async def release_for_review(self, checkpoint, **kwargs):
        checkpoint.current_unit_key = None
        checkpoint.claim_id = None
        checkpoint.status = CheckpointStatus.DISCOVERED
        return True

    async def advance(self, checkpoint, **kwargs):
        checkpoint.current_unit_key = None
        checkpoint.status = CheckpointStatus.DISCOVERED
        return True


class _PagedFetcher:
    def __init__(self, tmp_path):
        self.calls = []
        self.tmp_path = tmp_path

    async def fetch(self, config, reconciliation_date, fetch_metadata=None):
        metadata = fetch_metadata or {}
        self.calls.append(metadata)
        page = metadata.get("page", 1)
        local_path = self.tmp_path / f"page-{page}.json"
        local_path.write_text(f"page-{page}")
        unit = {
            "sourceUnitKey": f"unit-{page}",
            "sourceIdentity": {"page": page},
            "localPath": str(local_path),
            "page": page,
            "cursorBefore": metadata.get("cursor"),
            "cursorAfter": f"cursor-{page}" if page == 1 else None,
            "contentHash": f"hash-{page}",
        }
        return FetchResult(
            success=True,
            local_path=str(local_path),
            file_size=local_path.stat().st_size,
            metadata={
                "pagination": {
                    "has_more": page == 1,
                    "next_cursor": "cursor-1" if page == 1 else None,
                }
            },
            units=[unit],
        )


def test_scheduler_reuses_legacy_checkpoint_by_content_hash():
    checkpoint = SimpleNamespace(
        last_completed_unit_key="legacy-mtime-sensitive-key",
        high_water_mark={"contentHash": "same-content"},
    )
    units = [
        {
            "sourceUnitKey": "new-mtime-sensitive-key",
            "localPath": "/tmp/replayed.xlsx",
            "contentHash": "same-content",
        },
        {
            "sourceUnitKey": "next-file",
            "localPath": "/tmp/next.xlsx",
            "contentHash": "new-content",
        },
    ]

    remaining = _units_after_checkpoint(units, checkpoint)

    assert [unit.source_unit_key for unit in remaining] == ["next-file"]


def test_backfill_stream_identity_is_scoped_by_reconciliation_date() -> None:
    config = FetchConfig(
        partner="VIETTELPAY",
        fetchMethod=FetchMethod.API,
        api=APIConfig(baseUrl="https://partner.example/settlement"),
    )
    reconciliation_date = datetime(2026, 8, 9, tzinfo=UTC)

    scheduled = _stream_identity(
        config,
        mode=IngestionMode.SCHEDULED,
        reconciliation_date=reconciliation_date,
    )
    backfill = _stream_identity(
        config,
        mode=IngestionMode.BACKFILL,
        reconciliation_date=reconciliation_date,
    )

    assert scheduled["streamKey"].endswith("https://partner.example/settlement")
    assert backfill["streamKey"] == f'{scheduled["streamKey"]}:backfill:2026-08-09'


@pytest.mark.asyncio
async def test_blocked_stream_returns_non_retryable_checkpoint_result(tmp_path) -> None:
    config = FetchConfig(
        partner="VIETTELPAY",
        fetchMethod=FetchMethod.FILEDROP,
        cleanupAfterIngest=False,
        filedrop=FileDropConfig(directory=str(tmp_path)),
    )
    checkpoint_repo = _SequentialCheckpointRepository()
    checkpoint_repo.checkpoint = IngestionCheckpoint(
        partner=config.partner,
        fetchConfigId=str(config.id),
        sourceType="FILEDROP",
        streamKey="VIETTELPAY:FILEDROP:fixture",
        status=CheckpointStatus.BLOCKED,
        currentUnitKey="file:blocked.csv",
        lastCompletedUnitKey="file:previous.csv",
        errorCode="file_parse_error",
        retryable=False,
    )
    run = SimpleNamespace(id="runtime-blocked")

    with (
        patch("src.scheduler.jobs.create_runtime_run", new=AsyncMock(return_value=run)),
        patch("src.scheduler.jobs.update_runtime_run", new=AsyncMock()),
        patch("src.scheduler.jobs.IngestionCheckpointRepository", return_value=checkpoint_repo),
    ):
        result = await run_fetch_config_once(
            config=config,
            db=MagicMock(),
            config_loader=MagicMock(),
            reconciliation_date=datetime(2026, 8, 9, tzinfo=UTC),
        )

    assert result["outcome"] == "BLOCKED"
    assert result["errorCode"] == "file_parse_error"
    assert result["retryable"] is False
    assert result["checkpoint"]["currentUnitKey"] == "file:blocked.csv"


def test_file_read_failure_is_terminal_and_not_source_persist_error():
    result = SimpleNamespace(
        file_record=SimpleNamespace(stage_summary={"currentStage": "READING"}),
        errors=[{"field": "ingestion_error", "reason": "Invalid XLSX archive"}],
    )

    failure = _failed_ingestion_result(result)

    assert failure["errorCode"] == "file_parse_error"
    assert failure["retryable"] is False
    assert failure["error"] == "Invalid XLSX archive"


def test_persistence_failure_keeps_source_persist_error_retryability():
    result = SimpleNamespace(
        file_record=SimpleNamespace(stage_summary={"currentStage": "PERSISTING"}),
        errors=[{"field": "ingestion_error", "reason": "Database write failed"}],
    )

    failure = _failed_ingestion_result(result)

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

    failure = _failed_ingestion_result(result)

    assert failure["errorCode"] == "ingestion_key_error"
    assert failure["retryable"] is False
    assert "both id and trace are missing" in failure["error"]


@pytest.mark.asyncio
async def test_scheduler_fetches_and_ingests_api_pages_one_at_a_time(tmp_path):
    config = FetchConfig(
        partner="momo",
        fetch_method=FetchMethod.API,
        cleanup_after_ingest=False,
        api=APIConfig(
            base_url="https://api.example.com/settlement",
            pagination=APIPaginationConfig(
                page_param="page",
                cursor_param="cursor",
                items_path="data.items",
                next_cursor_path="data.nextCursor",
            ),
        ),
        validate_rows=True,
    )
    fetcher = _PagedFetcher(tmp_path)
    checkpoint_repo = _SequentialCheckpointRepository()
    ingested_paths = []
    health_check_flags = []
    validation_flags = []
    ingestion_result = SimpleNamespace(
        file_record=SimpleNamespace(
            id="file-1", processing_status=ProcessingStatus.COMPLETED
        ),
        stats=SimpleNamespace(
            total_rows=1, success_rows=1, duplicate_rows=0, failed_rows=0
        ),
        errors=[],
        outcome="INGESTED",
    )

    async def run_ingestion(**kwargs):
        ingested_paths.append(kwargs["file_path"])
        health_check_flags.append(kwargs["enable_config_health_check"])
        validation_flags.append(kwargs["validate_rows"])
        return ingestion_result

    run = SimpleNamespace(id="run-1")
    db = MagicMock()
    with (
        patch("src.scheduler.jobs.create_runtime_run", new=AsyncMock(return_value=run)),
        patch("src.scheduler.jobs.update_runtime_run", new=AsyncMock()),
        patch("src.scheduler.jobs.IngestionCheckpointRepository", return_value=checkpoint_repo),
        patch("src.scheduler.jobs.create_fetcher", return_value=fetcher),
        patch("src.scheduler.jobs._run_ingestion", new=run_ingestion),
        patch("src.scheduler.jobs.build_reconciliation_service") as reconciliation,
    ):
        reconciliation.return_value.execute = AsyncMock(return_value=["reconciliation-result"])
        result = await run_fetch_config_once(
            config=config,
            db=db,
            config_loader=MagicMock(),
            reconciliation_date=datetime(2024, 7, 7, tzinfo=UTC),
        )

    assert result["success"] is True
    assert [call.get("page", 1) for call in fetcher.calls] == [1, 2]
    assert all(call["singleUnit"] is True for call in fetcher.calls)
    assert [path.rsplit("/", 1)[-1] for path in ingested_paths] == [
        "page-1.json",
        "page-2.json",
    ]
    assert health_check_flags == [True, False]
    assert validation_flags == [True, True]
    assert checkpoint_repo.checkpoint.last_completed_unit_key == "unit-2"
    assert result["stats"]["reconciliationCount"] == 2
    commands = [call.args[0] for call in reconciliation.return_value.execute.await_args_list]
    assert [command.reconciliation_run_id for command in commands] == ["run-1", "run-1"]


@pytest.mark.asyncio
async def test_run_ingestion_disables_fast_mode_when_row_validation_is_enabled():
    result = SimpleNamespace(
        file_record=SimpleNamespace(processing_status=ProcessingStatus.COMPLETED),
        stats=SimpleNamespace(total_rows=1, success_rows=1, failed_rows=0),
    )
    pipeline = MagicMock()
    pipeline.process_file = AsyncMock(return_value=result)

    with patch("src.scheduler.jobs.build_ingestion_pipeline", return_value=pipeline) as build:
        output = await _run_ingestion(
            db=MagicMock(),
            config_loader=MagicMock(),
            file_path="/tmp/page-1.json",
            partner="VIETTELPAY",
            reconciliation_date=datetime(2026, 8, 9, tzinfo=UTC),
            validate_rows=True,
        )

    assert output is result
    assert build.call_args.kwargs["fast_mode"] is False


@pytest.mark.asyncio
async def test_scheduler_does_not_fetch_after_completed_api_stream_on_next_run(tmp_path):
    config = FetchConfig(
        partner="momo",
        fetch_method=FetchMethod.API,
        cleanup_after_ingest=False,
        api=APIConfig(
            base_url="https://api.example.com/settlement",
            pagination=APIPaginationConfig(
                page_param="page",
                cursor_param="cursor",
                items_path="data.items",
                next_cursor_path="data.nextCursor",
            ),
        ),
    )
    fetcher = _PagedFetcher(tmp_path)
    checkpoint_repo = _SequentialCheckpointRepository()
    ingestion_result = SimpleNamespace(
        file_record=SimpleNamespace(
            id="file-1", processing_status=ProcessingStatus.COMPLETED
        ),
        stats=SimpleNamespace(
            total_rows=1, success_rows=1, duplicate_rows=0, failed_rows=0
        ),
        errors=[],
        outcome="INGESTED",
    )

    async def run_ingestion(**_kwargs):
        return ingestion_result

    run = SimpleNamespace(id="run-completed-stream")
    db = MagicMock()
    with (
        patch("src.scheduler.jobs.create_runtime_run", new=AsyncMock(return_value=run)),
        patch("src.scheduler.jobs.update_runtime_run", new=AsyncMock()),
        patch("src.scheduler.jobs.IngestionCheckpointRepository", return_value=checkpoint_repo),
        patch("src.scheduler.jobs.create_fetcher", return_value=fetcher),
        patch("src.scheduler.jobs._run_ingestion", new=run_ingestion),
        patch("src.scheduler.jobs.build_reconciliation_service") as reconciliation,
    ):
        reconciliation.return_value.execute = AsyncMock(return_value=[])
        first = await run_fetch_config_once(
            config=config,
            db=db,
            config_loader=MagicMock(),
            reconciliation_date=datetime(2024, 7, 7, tzinfo=UTC),
        )
        second = await run_fetch_config_once(
            config=config,
            db=db,
            config_loader=MagicMock(),
            reconciliation_date=datetime(2024, 7, 7, tzinfo=UTC),
        )
        third = await run_fetch_config_once(
            config=config,
            db=db,
            config_loader=MagicMock(),
            reconciliation_date=datetime(2024, 7, 7, tzinfo=UTC),
        )

    assert first["success"] is True
    assert second["success"] is True
    assert third["outcome"] == "SAFE_DUPLICATE"
    assert third["safeDuplicate"] is True
    assert [call.get("page", 1) for call in fetcher.calls] == [1, 2]


@pytest.mark.asyncio
async def test_scheduler_keeps_run_waiting_for_configuration_review(tmp_path):
    config = FetchConfig(
        partner="momo",
        fetch_method=FetchMethod.API,
        cleanup_after_ingest=False,
        api=APIConfig(
            base_url="https://api.example.com/settlement",
            pagination=APIPaginationConfig(
                page_param="page",
                cursor_param="cursor",
                items_path="data.items",
                next_cursor_path="data.nextCursor",
            ),
        ),
    )
    fetcher = _PagedFetcher(tmp_path)
    checkpoint_repo = _SequentialCheckpointRepository()
    ingestion_result = SimpleNamespace(
        file_record=SimpleNamespace(
            id="file-pending", processing_status=ProcessingStatus.PENDING
        ),
        stats=SimpleNamespace(
            total_rows=0, success_rows=0, duplicate_rows=0, failed_rows=0
        ),
        errors=[
            {
                "field": "configApproval",
                "reason": "configuration approval required for partner=momo",
            }
        ],
        outcome="WAITING_REVIEW",
    )

    async def run_ingestion(**_kwargs):
        return ingestion_result

    run = SimpleNamespace(id="run-pending")
    db = MagicMock()
    with (
        patch("src.scheduler.jobs.create_runtime_run", new=AsyncMock(return_value=run)),
        patch("src.scheduler.jobs.update_runtime_run", new=AsyncMock()) as update_run,
        patch("src.scheduler.jobs.IngestionCheckpointRepository", return_value=checkpoint_repo),
        patch("src.scheduler.jobs.create_fetcher", return_value=fetcher),
        patch("src.scheduler.jobs._run_ingestion", new=run_ingestion),
    ):
        result = await run_fetch_config_once(
            config=config,
            db=db,
            config_loader=MagicMock(),
            reconciliation_date=datetime(2024, 7, 7, tzinfo=UTC),
        )

    assert result["success"] is True
    assert result["runtimeRun"]["status"] == "WAITING_REVIEW"
    assert any(
        call.kwargs.get("status") == "WAITING_REVIEW"
        for call in update_run.await_args_list
    )
    assert [call.get("page", 1) for call in fetcher.calls] == [1]


@pytest.mark.asyncio
async def test_scheduler_marks_checkpoint_filtered_units_as_safe_replay(tmp_path):
    config = FetchConfig(
        partner="momo",
        fetch_method=FetchMethod.FILEDROP,
        cleanup_after_ingest=False,
        filedrop=FileDropConfig(directory=str(tmp_path)),
    )
    fetcher = _PagedFetcher(tmp_path)
    checkpoint_repo = _SequentialCheckpointRepository()
    checkpoint_repo.checkpoint = IngestionCheckpoint(
        partner="momo",
        fetch_config_id=str(config.id),
        source_type="FILEDROP",
        stream_key="momo-filedrop",
        last_completed_unit_key="legacy-key",
        high_water_mark={"contentHash": "hash-1"},
        status=CheckpointStatus.COMPLETED,
    )
    run = SimpleNamespace(id="run-replay")

    with (
        patch("src.scheduler.jobs.create_runtime_run", new=AsyncMock(return_value=run)),
        patch("src.scheduler.jobs.update_runtime_run", new=AsyncMock()) as update_run,
        patch("src.scheduler.jobs.IngestionCheckpointRepository", return_value=checkpoint_repo),
        patch("src.scheduler.jobs.create_fetcher", return_value=fetcher),
        patch("src.scheduler.jobs._raw_stage_key") as raw_stage_key,
    ):
        result = await run_fetch_config_once(
            config=config,
            db=MagicMock(),
            config_loader=MagicMock(),
            reconciliation_date=datetime(2024, 7, 7, tzinfo=UTC),
        )

    assert result["success"] is True
    assert result["outcome"] == "FETCH_UNIT_REPLAY"
    assert result["reconciliationSkipped"] is True
    raw_stage_key.assert_not_called()
    assert any(
        call.kwargs.get("message")
        == "Fetch unit already processed. Ingestion and reconciliation were skipped safely."
        for call in update_run.await_args_list
    )


@pytest.mark.asyncio
async def test_airflow_execution_reraises_unexpected_error_after_runtime_failure(tmp_path):
    config = FetchConfig(
        partner="VIETTELPAY",
        fetchMethod=FetchMethod.FILEDROP,
        cleanupAfterIngest=False,
        filedrop=FileDropConfig(directory=str(tmp_path)),
    )
    fetcher = MagicMock()
    fetcher.fetch = AsyncMock(side_effect=RuntimeError("database connection lost"))
    checkpoint_repo = _SequentialCheckpointRepository()
    run = SimpleNamespace(id="runtime-airflow-error")

    with (
        patch("src.scheduler.jobs.create_runtime_run", new=AsyncMock(return_value=run)),
        patch("src.scheduler.jobs.update_runtime_run", new=AsyncMock()) as update_run,
        patch("src.scheduler.jobs.IngestionCheckpointRepository", return_value=checkpoint_repo),
        patch("src.scheduler.jobs.create_fetcher", return_value=fetcher),
    ):
        with pytest.raises(RuntimeError, match="database connection lost"):
            await run_fetch_config_once(
                config=config,
                db=MagicMock(),
                config_loader=MagicMock(),
                reconciliation_date=datetime(2026, 8, 9, tzinfo=UTC),
                raise_on_unexpected=True,
            )

    assert any(
        call.kwargs.get("status") == "FAILED"
        for call in update_run.await_args_list
    )
