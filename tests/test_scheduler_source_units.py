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
    IngestionCheckpoint,
)
from src.scheduler.jobs import _units_after_checkpoint, run_fetch_config_once


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
    )
    fetcher = _PagedFetcher(tmp_path)
    checkpoint_repo = _SequentialCheckpointRepository()
    ingested_paths = []
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
        return ingestion_result

    run = SimpleNamespace(id="run-1")
    db = MagicMock()
    with (
        patch("src.scheduler.jobs.create_runtime_run", new=AsyncMock(return_value=run)),
        patch("src.scheduler.jobs.update_runtime_run", new=AsyncMock()),
        patch("src.scheduler.jobs.IngestionCheckpointRepository", return_value=checkpoint_repo),
        patch("src.scheduler.jobs.create_fetcher", return_value=fetcher),
        patch("src.scheduler.jobs._run_ingestion", new=run_ingestion),
        patch("src.infrastructure.reconciliation.composition.ReconciliationEngine") as reconciliation,
    ):
        reconciliation.return_value.reconcile = AsyncMock(return_value=[])
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
    assert checkpoint_repo.checkpoint.last_completed_unit_key == "unit-2"


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
    assert any(
        call.kwargs.get("message")
        == "Fetch unit already processed. Ingestion and reconciliation were skipped safely."
        for call in update_run.await_args_list
    )
