import inspect

from src.application.automation.stream_lifecycle import checkpoint_short_circuit_result
from src.application.automation.stream_runner import run_source_stream, select_stream_runner


def test_stream_runner_keeps_airflow_call_contract():
    assert list(inspect.signature(run_source_stream).parameters) == [
        "config",
        "db",
        "config_loader",
        "reconciliation_date",
        "batch_size",
        "structured_logger",
        "mode",
        "runtime_run_id",
        "orchestration",
        "mapping_config_version",
        "backfill_run_id",
        "raise_on_unexpected",
    ]

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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
    IngestionMode,
    IngestionCheckpoint,
)


def test_stream_dispatcher_selects_paginated_and_file_runners():
    paginated = FetchConfig(
        partner="momo",
        fetch_method=FetchMethod.API,
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
    file_source = FetchConfig(
        partner="VIETTELPAY",
        fetch_method=FetchMethod.FILEDROP,
        filedrop=FileDropConfig(directory="/tmp/source-drop"),
    )

    assert select_stream_runner(paginated).__name__ == "run_paginated_stream"
    assert select_stream_runner(file_source).__name__ == "run_file_stream"


def test_lifecycle_preserves_blocked_and_completed_checkpoint_payloads():
    blocked = IngestionCheckpoint(
        partner="VIETTELPAY",
        fetch_config_id="config-1",
        source_type="FILEDROP",
        stream_key="VIETTELPAY:FILEDROP:fixture",
        status=CheckpointStatus.BLOCKED,
        current_unit_key="file:blocked.csv",
        error_code="file_parse_error",
    )
    completed = IngestionCheckpoint(
        partner="VIETTELPAY",
        fetch_config_id="config-1",
        source_type="API",
        stream_key="VIETTELPAY:API:fixture",
        stream_ended=True,
    )

    blocked_result = checkpoint_short_circuit_result(blocked)
    completed_result = checkpoint_short_circuit_result(completed)

    assert blocked_result == {
        "success": False,
        "outcome": "BLOCKED",
        "processed": 0,
        "failed": 1,
        "stoppedAt": "file:blocked.csv",
        "error": "Source stream is BLOCKED and requires operator resolution.",
        "errorCode": "file_parse_error",
        "retryable": False,
        "checkpoint": {
            "status": "BLOCKED",
            "currentUnitKey": "file:blocked.csv",
            "lastCompletedUnitKey": None,
            "cursorBefore": None,
            "cursorAfter": None,
        },
    }
    assert completed_result == {
        "success": True,
        "processed": 0,
        "failed": 0,
        "reconciliationSkipped": True,
        "streamAlreadyCompleted": True,
        "checkpoint": {
            "status": "ABSENT",
            "currentUnitKey": None,
            "lastCompletedUnitKey": None,
            "cursorBefore": None,
            "cursorAfter": None,
        },
    }


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
        patch("src.application.automation.stream_runner.create_runtime_run", new=AsyncMock(return_value=run)),
        patch("src.application.automation.stream_runtime.update_runtime_run", new=AsyncMock()),
        patch("src.application.automation.stream_runner.update_runtime_run", new=AsyncMock()),
        patch("src.application.automation.stream_runner.IngestionCheckpointRepository", return_value=checkpoint_repo),
    ):
        result = await run_source_stream(
            config=config,
            db=MagicMock(),
            config_loader=MagicMock(),
            reconciliation_date=datetime(2026, 8, 9, tzinfo=UTC),
        )

    assert result["outcome"] == "BLOCKED"
    assert result["errorCode"] == "file_parse_error"
    assert result["retryable"] is False
    assert result["checkpoint"]["currentUnitKey"] == "file:blocked.csv"


@pytest.mark.asyncio
async def test_stream_runner_fetches_and_ingests_api_pages_one_at_a_time(tmp_path):
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
        patch("src.application.automation.stream_runner.create_runtime_run", new=AsyncMock(return_value=run)),
        patch("src.application.automation.stream_runtime.update_runtime_run", new=AsyncMock()),
        patch("src.application.automation.stream_runner.update_runtime_run", new=AsyncMock()),
        patch("src.application.automation.stream_runner.IngestionCheckpointRepository", return_value=checkpoint_repo),
        patch("src.application.automation.stream_runner.create_fetcher", return_value=fetcher),
        patch("src.application.automation.stream_ingestion.run_ingestion", new=run_ingestion),
        patch("src.application.automation.stream_ingestion.build_reconciliation_service") as reconciliation,
    ):
        reconciliation.return_value.reconcile = AsyncMock(return_value=["reconciliation-result"])
        result = await run_source_stream(
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
    calls = reconciliation.return_value.reconcile.await_args_list
    assert [call.kwargs["reconciliation_run_id"] for call in calls] == ["run-1", "run-1"]


@pytest.mark.asyncio
async def test_backfill_with_approved_mapping_checks_each_day_for_structure_drift(tmp_path):
    config = FetchConfig(
        partner="VNPAY",
        fetch_method=FetchMethod.FILEDROP,
        cleanup_after_ingest=False,
        filedrop=FileDropConfig(directory=str(tmp_path)),
    )
    fetcher = _PagedFetcher(tmp_path)
    checkpoint_repo = _SequentialCheckpointRepository()
    health_check_flags = []
    ingestion_result = SimpleNamespace(
        file_record=SimpleNamespace(
            id="file-backfill-1", processing_status=ProcessingStatus.COMPLETED
        ),
        stats=SimpleNamespace(
            total_rows=1, success_rows=1, duplicate_rows=0, failed_rows=0
        ),
        errors=[],
        outcome="INGESTED",
    )

    async def run_ingestion(**kwargs):
        health_check_flags.append(kwargs["enable_config_health_check"])
        return ingestion_result

    run = SimpleNamespace(id="run-backfill-1")
    db = MagicMock()
    with (
        patch("src.application.automation.stream_runner.create_runtime_run", new=AsyncMock(return_value=run)),
        patch("src.application.automation.stream_runtime.update_runtime_run", new=AsyncMock()),
        patch("src.application.automation.stream_runner.update_runtime_run", new=AsyncMock()),
        patch("src.application.automation.stream_runner.IngestionCheckpointRepository", return_value=checkpoint_repo),
        patch("src.application.automation.stream_runner.create_fetcher", return_value=fetcher),
        patch("src.application.automation.stream_ingestion.run_ingestion", new=run_ingestion),
        patch("src.application.automation.stream_ingestion.build_reconciliation_service") as reconciliation,
    ):
        reconciliation.return_value.reconcile = AsyncMock(return_value=[])
        result = await run_source_stream(
            config=config,
            db=db,
            config_loader=MagicMock(),
            reconciliation_date=datetime(2026, 8, 13, tzinfo=UTC),
            mode=IngestionMode.BACKFILL,
            mapping_config_version="VNPAY_BACKFILL_V1",
            backfill_run_id="backfill-1",
        )

    assert result["success"] is True
    assert health_check_flags == [True]


@pytest.mark.asyncio
async def test_stream_runner_does_not_fetch_after_completed_api_stream_on_next_run(tmp_path):
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
        patch("src.application.automation.stream_runner.create_runtime_run", new=AsyncMock(return_value=run)),
        patch("src.application.automation.stream_runtime.update_runtime_run", new=AsyncMock()),
        patch("src.application.automation.stream_runner.update_runtime_run", new=AsyncMock()),
        patch("src.application.automation.stream_runner.IngestionCheckpointRepository", return_value=checkpoint_repo),
        patch("src.application.automation.stream_runner.create_fetcher", return_value=fetcher),
        patch("src.application.automation.stream_ingestion.run_ingestion", new=run_ingestion),
        patch("src.application.automation.stream_ingestion.build_reconciliation_service") as reconciliation,
    ):
        reconciliation.return_value.reconcile = AsyncMock(return_value=[])
        first = await run_source_stream(
            config=config,
            db=db,
            config_loader=MagicMock(),
            reconciliation_date=datetime(2024, 7, 7, tzinfo=UTC),
        )
        second = await run_source_stream(
            config=config,
            db=db,
            config_loader=MagicMock(),
            reconciliation_date=datetime(2024, 7, 7, tzinfo=UTC),
        )
        third = await run_source_stream(
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
async def test_stream_runner_returns_safe_duplicate_for_completed_legacy_api_stage(tmp_path):
    config = FetchConfig(
        partner="VIETTELPAY",
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
    checkpoint_repo = _SequentialCheckpointRepository()
    checkpoint_repo.checkpoint = IngestionCheckpoint(
        partner=config.partner,
        fetchConfigId=str(config.id),
        sourceType="API",
        streamKey="VIETTELPAY:API:https://api.example.com/settlement",
        status=CheckpointStatus.DISCOVERED,
    )
    completed_file = SimpleNamespace(processing_status=ProcessingStatus.COMPLETED)
    fetcher = _PagedFetcher(tmp_path)
    run = SimpleNamespace(id="run-legacy-duplicate")

    with (
        patch("src.application.automation.stream_runner.create_runtime_run", new=AsyncMock(return_value=run)),
        patch("src.application.automation.stream_runtime.update_runtime_run", new=AsyncMock()),
        patch("src.application.automation.stream_runner.update_runtime_run", new=AsyncMock()),
        patch("src.application.automation.stream_runner.IngestionCheckpointRepository", return_value=checkpoint_repo),
        patch("src.application.automation.stream_runner.ReconciliationFileRepository") as file_repo,
        patch("src.application.automation.stream_runner.create_fetcher", return_value=fetcher) as create_fetcher,
    ):
        file_repo.return_value.find_completed_by_raw_stage_key = AsyncMock(
            return_value=completed_file
        )
        result = await run_source_stream(
            config=config,
            db=MagicMock(),
            config_loader=MagicMock(),
            reconciliation_date=datetime(2024, 7, 7, tzinfo=UTC),
        )

    assert result["outcome"] == "SAFE_DUPLICATE"
    assert result["safeDuplicate"] is True
    create_fetcher.assert_not_called()


@pytest.mark.asyncio
async def test_stream_runner_keeps_run_waiting_for_configuration_review(tmp_path):
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
        patch("src.application.automation.stream_runner.create_runtime_run", new=AsyncMock(return_value=run)),
        patch("src.application.automation.stream_runtime.update_runtime_run", new=AsyncMock()) as update_run,
        patch("src.application.automation.stream_runner.update_runtime_run", new=AsyncMock()),
        patch("src.application.automation.stream_runner.IngestionCheckpointRepository", return_value=checkpoint_repo),
        patch("src.application.automation.stream_runner.create_fetcher", return_value=fetcher),
        patch("src.application.automation.stream_ingestion.run_ingestion", new=run_ingestion),
    ):
        result = await run_source_stream(
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
async def test_stream_runner_marks_checkpoint_filtered_units_as_safe_replay(tmp_path):
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
        patch("src.application.automation.stream_runner.create_runtime_run", new=AsyncMock(return_value=run)),
        patch("src.application.automation.stream_runtime.update_runtime_run", new=AsyncMock()) as update_run,
        patch("src.application.automation.stream_runner.update_runtime_run", new=AsyncMock()),
        patch("src.application.automation.stream_runner.IngestionCheckpointRepository", return_value=checkpoint_repo),
        patch("src.application.automation.stream_runner.create_fetcher", return_value=fetcher),
        patch("src.application.automation.stream_runner.build_raw_stage_key") as raw_stage_key,
    ):
        result = await run_source_stream(
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
        patch("src.application.automation.stream_runner.create_runtime_run", new=AsyncMock(return_value=run)),
        patch("src.application.automation.stream_runtime.update_runtime_run", new=AsyncMock()) as update_run,
        patch("src.application.automation.stream_runner.update_runtime_run", new=AsyncMock()),
        patch("src.application.automation.stream_runner.IngestionCheckpointRepository", return_value=checkpoint_repo),
        patch("src.application.automation.stream_runner.create_fetcher", return_value=fetcher),
    ):
        with pytest.raises(RuntimeError, match="database connection lost"):
            await run_source_stream(
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
