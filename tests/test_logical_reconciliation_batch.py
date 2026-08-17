"""Regression tests for stream-level reconciliation file grouping."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.enums import ProcessingStatus
from src.application.review.reprocessing import reprocess_staged_pages


def _pages():
    return [
        SimpleNamespace(
            id=f"raw-page-{index}",
            page=index,
            local_path=f"page-{index}.json",
            source_unit_key=f"unit-{index}",
            cursor_before=f"cursor-{index - 1}",
            cursor_after=f"cursor-{index}" if index < 3 else None,
            content_hash=f"hash-{index}",
            has_more=index < 3,
            partner="VIETTELPAY",
            fetch_config_id="config-viettelpay",
            source_type="API",
            stream_key="VIETTELPAY:API:https://partner.example/settlement",
            reconciliation_date=datetime(2026, 8, 11, tzinfo=timezone.utc),
            sample_rows=[],
        )
        for index in range(1, 4)
    ]


def _packet():
    return SimpleNamespace(
        id="packet-1",
        partner="VIETTELPAY",
        file_name="viettelpay.json",
        raw_stage_key="stream-1",
        scope_type="FULL_SNAPSHOT",
        reconciliation_date=datetime(2026, 8, 11, tzinfo=timezone.utc),
    )


def _config():
    return SimpleNamespace(
        id="mapping-1",
        partner="VIETTELPAY",
        workflow_type="API",
        file_type="JSON",
        config_version="mapping-v1",
    )


def _ingestion_result(file_id: str, *, status=ProcessingStatus.COMPLETED, row_count=2):
    return SimpleNamespace(
        file_record=SimpleNamespace(id=file_id, processing_status=status),
        stats=SimpleNamespace(
            total_rows=row_count,
            success_rows=row_count if status == ProcessingStatus.COMPLETED else 0,
            duplicate_rows=0,
            failed_rows=0 if status == ProcessingStatus.COMPLETED else row_count,
        ),
        ingestion_keys=[f"{file_id}-key-1", f"{file_id}-key-2"],
        errors=[] if status == ProcessingStatus.COMPLETED else [{"reason": "page failed"}],
    )


def _harness(results):
    raw_repo = MagicMock()
    raw_repo.find_for_replay = AsyncMock(return_value=_pages())
    raw_repo.materialize = AsyncMock(side_effect=lambda page, destination: destination)
    raw_repo.mark_consumed = AsyncMock()

    file_repo = MagicMock()
    file_repo.find_many = AsyncMock(return_value=[])
    file_repo.collection.delete_many = AsyncMock()
    file_repo.update_one = AsyncMock()
    file_repo.update_processing_stats = AsyncMock()
    file_repo.update_status = AsyncMock()
    file_repo.update_stage_summary = AsyncMock()
    file_repo.delete_one = AsyncMock()

    transaction_repo = MagicMock()
    transaction_repo.delete_by_source_file = AsyncMock()
    transaction_repo.rebind_source_file = AsyncMock()

    result_repo = MagicMock()
    result_repo.delete_by_partner_and_date = AsyncMock()

    pipeline = MagicMock()
    pipeline.process_file = AsyncMock(side_effect=results)

    reconciliation = MagicMock()
    reconciliation.execute = AsyncMock(return_value=[object()] * 6)

    return (
        raw_repo,
        file_repo,
        transaction_repo,
        result_repo,
        pipeline,
        reconciliation,
    )


@pytest.mark.asyncio
async def test_three_pages_share_one_file_and_reconcile_once():
    harness = _harness(
        [
            _ingestion_result("page-file-1"),
            _ingestion_result("page-file-2"),
            _ingestion_result("page-file-3"),
        ]
    )
    raw_repo, file_repo, transaction_repo, result_repo, pipeline, reconciliation = harness

    with (
        patch("src.application.review.reprocessing.RawIngestionPageRepository", return_value=raw_repo),
        patch("src.application.review.reprocessing.ReconciliationFileRepository", return_value=file_repo),
        patch("src.application.review.reprocessing.DataContainerRepository", return_value=transaction_repo),
        patch("src.application.review.reprocessing.ReconciliationResultRepository", return_value=result_repo),
        patch("src.application.review.reprocessing.build_ingestion_pipeline", return_value=pipeline),
        patch("src.application.review.reprocessing.build_reconciliation_service", return_value=reconciliation),
        patch("src.application.review.reprocessing.build_config_loader", return_value=MagicMock()),
        patch("src.application.review.reprocessing.update_runtime_run", new=AsyncMock()),
        patch("src.application.review.reprocessing._update_post_approval_run", new=AsyncMock()),
    ):
        result = await reprocess_staged_pages(
            db=MagicMock(),
            packet=_packet(),
            config=_config(),
            run_id="post-approval-1",
            runtime_run_id="runtime-1",
            raw_stage_key="stream-1",
        )

    assert result["ok"] is True
    assert result["fileId"] == "page-file-1"
    assert result["stats"]["pageCount"] == 3
    assert result["stats"]["totalRows"] == 6
    reconciliation.execute.assert_awaited_once()
    command = reconciliation.execute.await_args.args[0]
    assert command.source_file_id == "page-file-1"
    assert transaction_repo.rebind_source_file.await_count == 2
    assert file_repo.delete_one.await_count == 2


@pytest.mark.asyncio
async def test_successful_staged_replay_finalizes_scheduled_checkpoint():
    harness = _harness(
        [
            _ingestion_result("page-file-1"),
            _ingestion_result("page-file-2"),
            _ingestion_result("page-file-3"),
        ]
    )
    raw_repo, file_repo, transaction_repo, result_repo, pipeline, reconciliation = harness
    checkpoint_repo = MagicMock()
    checkpoint_repo.find_by_stream = AsyncMock(return_value=SimpleNamespace(id="checkpoint-1"))
    checkpoint_repo.mark_stream_completed_after_review = AsyncMock(return_value=True)

    with (
        patch("src.application.review.reprocessing.RawIngestionPageRepository", return_value=raw_repo),
        patch("src.application.review.reprocessing.ReconciliationFileRepository", return_value=file_repo),
        patch("src.application.review.reprocessing.DataContainerRepository", return_value=transaction_repo),
        patch("src.application.review.reprocessing.ReconciliationResultRepository", return_value=result_repo),
        patch("src.application.review.reprocessing.build_ingestion_pipeline", return_value=pipeline),
        patch("src.application.review.reprocessing.build_reconciliation_service", return_value=reconciliation),
        patch("src.application.review.reprocessing.build_config_loader", return_value=MagicMock()),
        patch("src.application.review.reprocessing.update_runtime_run", new=AsyncMock()),
        patch("src.application.review.reprocessing._update_post_approval_run", new=AsyncMock()),
        patch("src.application.review.staged_page_replay.IngestionCheckpointRepository", return_value=checkpoint_repo),
    ):
        result = await reprocess_staged_pages(
            db=MagicMock(),
            packet=_packet(),
            config=_config(),
            run_id="post-approval-1",
            runtime_run_id="runtime-1",
            raw_stage_key="stream-1",
        )

    assert result["ok"] is True
    checkpoint_repo.mark_stream_completed_after_review.assert_awaited_once()
    kwargs = checkpoint_repo.mark_stream_completed_after_review.await_args.kwargs
    assert kwargs["unit_key"] == "unit-3"
    assert kwargs["high_water_mark"] == {
        "sourceUnitKey": "unit-3",
        "page": 3,
        "cursorAfter": None,
        "contentHash": "hash-3",
        "hasMore": False,
    }


@pytest.mark.asyncio
async def test_failed_middle_page_stops_before_reconciliation():
    harness = _harness(
        [
            _ingestion_result("page-file-1"),
            _ingestion_result("page-file-2", status=ProcessingStatus.FAILED),
            _ingestion_result("page-file-3"),
        ]
    )
    raw_repo, file_repo, transaction_repo, result_repo, pipeline, reconciliation = harness

    with (
        patch("src.application.review.reprocessing.RawIngestionPageRepository", return_value=raw_repo),
        patch("src.application.review.reprocessing.ReconciliationFileRepository", return_value=file_repo),
        patch("src.application.review.reprocessing.DataContainerRepository", return_value=transaction_repo),
        patch("src.application.review.reprocessing.ReconciliationResultRepository", return_value=result_repo),
        patch("src.application.review.reprocessing.build_ingestion_pipeline", return_value=pipeline),
        patch("src.application.review.reprocessing.build_config_loader", return_value=MagicMock()),
        patch("src.application.review.reprocessing.update_runtime_run", new=AsyncMock()),
        patch("src.application.review.reprocessing._update_post_approval_run", new=AsyncMock()),
    ):
        result = await reprocess_staged_pages(
            db=MagicMock(),
            packet=_packet(),
            config=_config(),
            run_id="post-approval-1",
            runtime_run_id="runtime-1",
            raw_stage_key="stream-1",
        )

    assert result["ok"] is False
    assert pipeline.process_file.await_count == 2
    reconciliation.execute.assert_not_awaited()
    transaction_repo.delete_by_source_file.assert_awaited()


@pytest.mark.asyncio
async def test_reconciliation_failure_marks_logical_batch_failed():
    harness = _harness(
        [
            _ingestion_result("page-file-1"),
            _ingestion_result("page-file-2"),
            _ingestion_result("page-file-3"),
        ]
    )
    raw_repo, file_repo, transaction_repo, result_repo, pipeline, reconciliation = harness
    reconciliation.execute = AsyncMock(side_effect=RuntimeError("reconciliation failed"))

    with (
        patch("src.application.review.reprocessing.RawIngestionPageRepository", return_value=raw_repo),
        patch("src.application.review.reprocessing.ReconciliationFileRepository", return_value=file_repo),
        patch("src.application.review.reprocessing.DataContainerRepository", return_value=transaction_repo),
        patch("src.application.review.reprocessing.ReconciliationResultRepository", return_value=result_repo),
        patch("src.application.review.reprocessing.build_ingestion_pipeline", return_value=pipeline),
        patch("src.application.review.reprocessing.build_reconciliation_service", return_value=reconciliation),
        patch("src.application.review.reprocessing.build_config_loader", return_value=MagicMock()),
        patch("src.application.review.reprocessing.update_runtime_run", new=AsyncMock()),
        patch("src.application.review.reprocessing._update_post_approval_run", new=AsyncMock()),
    ):
        result = await reprocess_staged_pages(
            db=MagicMock(),
            packet=_packet(),
            config=_config(),
            run_id="post-approval-1",
            runtime_run_id="runtime-1",
            raw_stage_key="stream-1",
        )

    reconciliation.execute.assert_awaited_once()
    assert result["ok"] is False
    assert result["stage"] == "reconciliation"
    transaction_repo.delete_by_source_file.assert_awaited()
