from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.ingestion.raw_pages import RawPageStatus
from src.domain.ingestion.source_units import SourceUnitMetadata
from src.infrastructure.ingestion.raw_page_repository import RawIngestionPageRepository
from src.domain.fetch_config.models import APIConfig, APIPaginationConfig, FetchConfig, FetchMethod
from src.domain.ingestion.checkpoints import CheckpointStatus, IngestionCheckpoint
from src.fetchers.base import FetchResult
from src.application.automation.stream_runner import run_source_stream
from src.config.config_health import ConfigurationApprovalRequiredError


@pytest.mark.asyncio
async def test_stage_from_path_uploads_once_and_keeps_payload_outside_metadata(tmp_path):
    payload_path = tmp_path / "page-1.json"
    payload_path.write_bytes(b'{"items":[{"id":"VTP-001"}]}')
    bucket = MagicMock()
    bucket.upload_from_stream = AsyncMock(return_value="gridfs-page-1")

    unit = SourceUnitMetadata(
        sourceUnitKey="vtp:2024-07-07:page-1",
        localPath=str(payload_path),
        page=1,
        itemCount=1,
        contentHash="hash-1",
        fetchMetadata={"sampleRows": [{"id": "VTP-001"}]},
    )
    repo = RawIngestionPageRepository.__new__(RawIngestionPageRepository)
    repo.collection = MagicMock()
    repo._bucket = bucket
    repo.find_one = AsyncMock(return_value=None)
    repo.create = AsyncMock(side_effect=lambda page: page)

    page = await repo.stage_from_path(
        stage_key="VIETTELPAY:2024-07-07:v1",
        partner="VIETTELPAY",
        fetch_config_id="cfg-1",
        source_type="API",
        stream_key="vtp-api",
        reconciliation_date=datetime(2024, 7, 7, tzinfo=UTC),
        unit=unit,
    )

    bucket.upload_from_stream.assert_awaited_once()
    assert page.status == RawPageStatus.STAGED
    assert page.gridfs_file_id == "gridfs-page-1"
    assert page.sample_rows == [{"id": "VTP-001"}]
    stored = page.model_dump(by_alias=True)
    assert "payload" not in stored
    assert "raw" not in stored


@pytest.mark.asyncio
async def test_stage_is_idempotent_when_source_unit_already_exists(tmp_path):
    repo = RawIngestionPageRepository.__new__(RawIngestionPageRepository)
    existing = MagicMock(source_unit_key="unit-1", status=RawPageStatus.STAGED)
    repo.find_one = AsyncMock(return_value=existing)
    repo._bucket = MagicMock()
    unit = SourceUnitMetadata(sourceUnitKey="unit-1", localPath=str(tmp_path / "missing"))

    result = await repo.stage_from_path(
        stage_key="stage-1",
        partner="VTP",
        fetch_config_id="cfg",
        source_type="API",
        stream_key="stream",
        reconciliation_date=datetime.now(UTC),
        unit=unit,
    )

    assert result is existing
    repo._bucket.upload_from_stream.assert_not_called()


@pytest.mark.asyncio
async def test_stage_cleans_gridfs_payload_when_metadata_insert_races(tmp_path):
    payload_path = tmp_path / "page-1.json"
    payload_path.write_bytes(b'{"items": []}')
    bucket = MagicMock()
    bucket.upload_from_stream = AsyncMock(return_value="orphan-file")
    bucket.delete = AsyncMock()
    existing = MagicMock(source_unit_key="unit-1", status=RawPageStatus.STAGED)
    repo = RawIngestionPageRepository.__new__(RawIngestionPageRepository)
    repo._bucket = bucket
    repo.find_one = AsyncMock(side_effect=[None, existing])
    repo.create = AsyncMock(side_effect=RuntimeError("duplicate key"))
    unit = SourceUnitMetadata(sourceUnitKey="unit-1", localPath=str(payload_path))

    result = await repo.stage_from_path(
        stage_key="stage-1",
        partner="VTP",
        fetch_config_id="cfg",
        source_type="API",
        stream_key="stream",
        reconciliation_date=datetime.now(UTC),
        unit=unit,
    )

    assert result is existing
    bucket.delete.assert_awaited_once_with("orphan-file")


def test_raw_page_indexes_are_declared():
    from src.models.indexes import INDEXES

    assert "raw_ingestion_page" in INDEXES
    assert any(
        idx.document.get("unique") and "sourceUnitKey" in idx.document["key"]
        for idx in INDEXES["raw_ingestion_page"]
    )


@pytest.mark.asyncio
async def test_scheduler_stages_all_pages_before_waiting_for_mapping(tmp_path):
    config = FetchConfig(
        partner="VIETTELPAY",
        fetchMethod=FetchMethod.API,
        cleanupAfterIngest=False,
        api=APIConfig(
            baseUrl="https://partner.example/settlement",
            pagination=APIPaginationConfig(
                pageParam="page", cursorParam="cursor",
                itemsPath="data.items", nextCursorPath="data.nextCursor",
            ),
        ),
    )
    calls: list[dict] = []

    class Fetcher:
        async def fetch(self, _config, _date, fetch_metadata=None):
            fetch_metadata = fetch_metadata or {}
            page = fetch_metadata.get("page", 1)
            path = tmp_path / f"page-{page}.json"
            path.write_text(f"{{\"items\":[{{\"id\":{page}}}]}}")
            calls.append(fetch_metadata)
            unit = {
                "sourceUnitKey": f"unit-{page}", "localPath": str(path),
                "page": page, "cursorAfter": "cursor-1" if page == 1 else None,
                "contentHash": f"hash-{page}",
                "fetchMetadata": {"sampleRows": [{"id": page}]},
            }
            return FetchResult(
                success=True, local_path=str(path), units=[unit],
                metadata={"pagination": {"has_more": page == 1}},
            )

    class Checkpoints:
        def __init__(self):
            self.checkpoint = None
            self.claim_calls = 0

        async def find_by_stream(self, **_kwargs):
            return self.checkpoint

        async def claim_unit(self, **kwargs):
            self.checkpoint = IngestionCheckpoint(
                partner=kwargs["partner"], fetchConfigId=kwargs["fetch_config_id"],
                sourceType=kwargs["source_type"], streamKey=kwargs["stream_key"],
                currentUnitKey=kwargs["unit_key"], status=CheckpointStatus.PROCESSING,
                claimId="claim",
            )
            return self.checkpoint, True

        async def release_for_review(self, *_args, **_kwargs):
            return True

    staged = []
    raw_repo = MagicMock()
    raw_repo.stage_from_path = AsyncMock(side_effect=lambda **kwargs: staged.append(kwargs))
    raw_repo.mark_consumed = AsyncMock()
    run = MagicMock(id="runtime")
    run_ingestion = AsyncMock()

    with (
        patch("src.application.automation.stream_runner.RawIngestionPageRepository", return_value=raw_repo),
        patch("src.application.automation.stream_runner.create_runtime_run", new=AsyncMock(return_value=run)),
        patch("src.application.automation.stream_runtime.update_runtime_run", new=AsyncMock()),
        patch("src.application.automation.stream_runner.update_runtime_run", new=AsyncMock()),
        patch("src.application.automation.stream_runner.IngestionCheckpointRepository", return_value=Checkpoints()),
        patch("src.application.automation.stream_runner.create_fetcher", return_value=Fetcher()),
        patch(
            "src.application.automation.stream_runner.check_and_refresh_config",
            new=AsyncMock(side_effect=ConfigurationApprovalRequiredError("mapping required")),
        ) as preflight,
        patch("src.application.automation.stream_ingestion.run_ingestion", new=run_ingestion),
    ):
        result = await run_source_stream(
            config=config, db=MagicMock(), config_loader=MagicMock(),
            reconciliation_date=datetime(2024, 7, 7, tzinfo=UTC),
        )

    assert result["runtimeRun"]["status"] == "WAITING_REVIEW"
    assert result["fetchedUnitCount"] == 2
    assert result["totalUnitCount"] == 2
    assert [call.get("page", 1) for call in calls] == [1, 2]
    assert [item["unit"].page for item in staged] == [1, 2]
    assert raw_repo.mark_consumed.await_count == 0
    run_ingestion.assert_not_awaited()
    assert preflight.await_args.kwargs["raw_stage_key"]
    assert preflight.await_args.kwargs.get("config_version") is None


@pytest.mark.asyncio
async def test_scheduler_sends_complete_paginated_stream_to_scope_review_with_approved_mapping(tmp_path):
    """An approved mapping must not bypass the stream-level scope decision."""
    config = FetchConfig(
        partner="VIETTELPAY",
        fetchMethod=FetchMethod.API,
        cleanupAfterIngest=False,
        api=APIConfig(
            baseUrl="https://partner.example/settlement",
            pagination=APIPaginationConfig(
                pageParam="page", cursorParam="cursor",
                itemsPath="data.items", nextCursorPath="data.nextCursor",
            ),
        ),
    )

    class Fetcher:
        async def fetch(self, _config, _date, fetch_metadata=None):
            page = (fetch_metadata or {}).get("page", 1)
            path = tmp_path / f"page-{page}.json"
            path.write_text(f'{{"items":[{{"id":{page}}}]}}')
            return FetchResult(
                success=True,
                local_path=str(path),
                units=[{
                    "sourceUnitKey": f"unit-{page}", "localPath": str(path),
                    "page": page, "cursorAfter": "cursor-1" if page == 1 else None,
                    "contentHash": f"hash-{page}",
                }],
                metadata={"pagination": {"has_more": page == 1}},
            )

    class Checkpoints:
        checkpoint = None

        async def find_by_stream(self, **_kwargs):
            return self.checkpoint

        async def claim_unit(self, **kwargs):
            self.checkpoint = IngestionCheckpoint(
                partner=kwargs["partner"], fetchConfigId=kwargs["fetch_config_id"],
                sourceType=kwargs["source_type"], streamKey=kwargs["stream_key"],
                currentUnitKey=kwargs["unit_key"], status=CheckpointStatus.PROCESSING,
                claimId="claim",
            )
            return self.checkpoint, True

        async def release_for_review(self, *_args, **_kwargs):
            return True

    raw_repo = MagicMock()
    raw_repo.stage_from_path = AsyncMock()
    raw_repo.mark_consumed = AsyncMock()
    approved_mapping = MagicMock(id="mapping-approved")
    create_packet = AsyncMock()

    with (
        patch("src.application.automation.stream_runner.RawIngestionPageRepository", return_value=raw_repo),
        patch("src.application.automation.stream_runner.create_runtime_run", new=AsyncMock(return_value=MagicMock(id="runtime"))),
        patch("src.application.automation.stream_runtime.update_runtime_run", new=AsyncMock()),
        patch("src.application.automation.stream_runner.update_runtime_run", new=AsyncMock()),
        patch("src.application.automation.stream_runner.IngestionCheckpointRepository", return_value=Checkpoints()),
        patch("src.application.automation.stream_runner.create_fetcher", return_value=Fetcher()),
        patch("src.application.automation.stream_runner.check_and_refresh_config", new=AsyncMock(return_value=approved_mapping)),
        patch("src.application.automation.stream_runner.create_stream_scope_review_packet", new=create_packet),
        patch("src.application.automation.stream_ingestion.run_ingestion", new=AsyncMock()) as run_ingestion,
    ):
        result = await run_source_stream(
            config=config, db=MagicMock(), config_loader=MagicMock(),
            reconciliation_date=datetime(2024, 7, 7, tzinfo=UTC),
        )

    assert result["runtimeRun"]["status"] == "WAITING_REVIEW"
    assert result["fetchedUnitCount"] == 2
    create_packet.assert_awaited_once()
    assert create_packet.await_args.kwargs["raw_stage_key"]
    assert create_packet.await_args.kwargs["active_runtime_config"] is approved_mapping
    run_ingestion.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_page_does_not_create_review_packet(tmp_path):
    config = FetchConfig(
        partner="VIETTELPAY",
        fetchMethod=FetchMethod.API,
        cleanupAfterIngest=False,
        api=APIConfig(
            baseUrl="https://partner.example/settlement",
            pagination=APIPaginationConfig(
                pageParam="page", cursorParam="cursor",
                itemsPath="data.items", nextCursorPath="data.nextCursor",
            ),
        ),
    )

    class FailingFetcher:
        def __init__(self):
            self.page = 0

        async def fetch(self, _config, _date, fetch_metadata=None):
            self.page += 1
            path = tmp_path / f"page-{self.page}.json"
            path.write_text("{\"items\":[]}")
            if self.page == 1:
                return FetchResult(
                    success=True, local_path=str(path),
                    units=[{
                        "sourceUnitKey": "unit-1", "localPath": str(path),
                        "page": 1, "cursorAfter": "cursor-1", "contentHash": "hash-1",
                    }],
                    metadata={"pagination": {"has_more": True}},
                )
            return FetchResult(
                success=False, error="partner returned 504",
                units=[{
                    "sourceUnitKey": "unit-2", "localPath": str(path),
                    "page": 2, "contentHash": "hash-2", "status": "FAILED",
                    "errorCode": "fetch_http_5xx",
                }],
                metadata={"pagination": {"units": []}},
            )

    raw_repo = MagicMock()
    staged = []
    raw_repo.stage_from_path = AsyncMock(side_effect=lambda **kwargs: staged.append(kwargs))
    raw_repo.mark_consumed = AsyncMock()
    run = MagicMock(id="runtime")

    class Checkpoints:
        def __init__(self):
            self.checkpoint = None
            self.claim_calls = 0

        async def find_by_stream(self, **_kwargs):
            return self.checkpoint

        async def claim_unit(self, **kwargs):
            self.claim_calls += 1
            self.checkpoint = MagicMock(
                current_unit_key=kwargs["unit_key"],
                claim_id="claim", attempt_count=1,
                last_completed_unit_key=None,
            )
            return self.checkpoint, True

        async def mark_failed(self, *_args, **_kwargs):
            return True

    with (
        patch("src.application.automation.stream_runner.RawIngestionPageRepository", return_value=raw_repo),
        patch("src.application.automation.stream_runner.create_runtime_run", new=AsyncMock(return_value=run)),
        patch("src.application.automation.stream_runtime.update_runtime_run", new=AsyncMock()),
        patch("src.application.automation.stream_runner.update_runtime_run", new=AsyncMock()),
        patch("src.application.automation.stream_runner.IngestionCheckpointRepository", return_value=Checkpoints()) as checkpoint_repo,
        patch("src.application.automation.stream_runner.create_fetcher", return_value=FailingFetcher()),
        patch("src.application.automation.stream_runner.check_and_refresh_config", new=AsyncMock()) as preflight,
        patch("src.application.automation.stream_ingestion.run_ingestion", new=AsyncMock()) as run_ingestion,
    ):
        result = await run_source_stream(
            config=config, db=MagicMock(), config_loader=MagicMock(),
            reconciliation_date=datetime(2024, 7, 7, tzinfo=UTC),
        )

    assert result["success"] is False
    assert result["error"] == "partner returned 504"
    assert result["errorCode"] == "fetch_http_5xx"
    assert result["fetchedUnitCount"] == 1
    assert len(staged) == 1
    assert checkpoint_repo.return_value.claim_calls == 0
    preflight.assert_not_awaited()
    run_ingestion.assert_not_awaited()
