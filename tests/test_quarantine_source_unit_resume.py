"""TDD contracts for production quarantine-driven source-unit resume."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.domain.fetch_config.models import APIConfig, APIPaginationConfig, FetchConfig, FetchMethod
from src.domain.ingestion.checkpoints import CheckpointStatus, IngestionCheckpoint, IngestionMode
from src.domain.ingestion.raw_pages import RawIngestionPage
from src.domain.ingestion.models import ReconciliationFile


def _checkpoint() -> IngestionCheckpoint:
    return IngestionCheckpoint(
        partner="MOMO",
        fetchConfigId="fetch-1",
        sourceType="API",
        streamKey="MOMO:API:https://partner.example/settlements",
        mode=IngestionMode.SCHEDULED,
        status=CheckpointStatus.DISCOVERED,
        configVersion="stream-version",
        sourceEndpoint="https://partner.example/settlements",
    )


def _fetch_config() -> FetchConfig:
    return FetchConfig(
        _id=uuid4(),
        partner="MOMO",
        fetchMethod=FetchMethod.API,
        api=APIConfig(
            baseUrl="https://partner.example/settlements",
            pagination=APIPaginationConfig(
                pageParam="page",
                cursorParam="cursor",
                itemsPath="items",
                nextCursorPath="nextCursor",
            ),
        ),
    )


@pytest.mark.asyncio
async def test_production_resume_rebuilds_raw_unit_and_delegates_to_checkpoint_flow():
    from src.application.ingestion.source_unit_resume import resume_quarantined_source_unit

    checkpoint_repo = MagicMock()
    checkpoint_repo.find_by_source_unit_key = AsyncMock(return_value=_checkpoint())
    raw_page_repo = MagicMock()
    raw_page_repo.find_one = AsyncMock(
        return_value=RawIngestionPage(
            stageKey="stage-1",
            partner="MOMO",
            fetchConfigId="fetch-1",
            sourceType="API",
            streamKey="MOMO:API:https://partner.example/settlements",
            reconciliationDate=datetime(2026, 8, 26, tzinfo=UTC),
            sourceUnitKey="unit-1",
            page=3,
            cursorBefore="cursor-2",
            cursorAfter="cursor-3",
            itemCount=10,
            hasMore=False,
            sampleRows=[{"id": "TX-1"}],
            localPath="/tmp/page-3.json",
        )
    )
    quarantine_repo = MagicMock()
    quarantine_repo.find_many = AsyncMock(return_value=([], None))
    source_file_repo = MagicMock()
    source_file_repo.find_by_fetch_unit_key = AsyncMock(return_value=None)
    fetch_repo = MagicMock()
    fetch_repo.find_by_id = AsyncMock(return_value=_fetch_config())
    ingest_unit = AsyncMock()
    audit = AsyncMock()

    with (
        patch(
            "src.application.ingestion.source_unit_resume.IngestionCheckpointRepository",
            return_value=checkpoint_repo,
        ),
        patch(
            "src.application.ingestion.source_unit_resume.RawIngestionPageRepository",
            return_value=raw_page_repo,
        ),
        patch(
            "src.application.ingestion.source_unit_resume.IngestionQuarantineRepository",
            return_value=quarantine_repo,
        ),
        patch(
            "src.application.ingestion.source_unit_resume.ReconciliationFileRepository",
            return_value=source_file_repo,
        ),
        patch(
            "src.application.ingestion.source_unit_resume.FetchConfigRepository",
            return_value=fetch_repo,
        ),
        patch(
            "src.application.ingestion.source_unit_resume.build_source_unit_ingestor",
            return_value=(ingest_unit, {}),
        ),
        patch(
            "src.application.ingestion.source_unit_resume.build_config_loader",
            return_value=MagicMock(),
        ),
        patch(
            "src.application.ingestion.source_unit_resume.resume_held_source_unit",
            new=AsyncMock(return_value={"success": True, "processed": 1}),
        ) as resume,
    ):
        result = await resume_quarantined_source_unit(
            object(),
            "unit-1",
            operator_id="operator-1",
            reason="Conflict records resolved",
            action_id="resume-1",
            audit_recorder=audit,
        )

    assert result == {"success": True, "processed": 1}
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["action"] == "QUARANTINE_SOURCE_UNIT_RESUMED"
    assert audit.await_args.kwargs["metadata"]["actionId"] == "resume-1"
    assert "sourceUnitKey" in audit.await_args.kwargs["metadata"]
    call = resume.await_args
    assert call.kwargs["source_unit_key"] == "unit-1"
    assert call.kwargs["stream_identity"] == {
        "partner": "MOMO",
        "fetchConfigId": "fetch-1",
        "sourceType": "API",
        "streamKey": "MOMO:API:https://partner.example/settlements",
        "configVersion": "stream-version",
        "sourceEndpoint": "https://partner.example/settlements",
    }
    assert call.kwargs["unit"].source_unit_key == "unit-1"
    assert call.kwargs["unit"].page == 3
    assert call.kwargs["unit"].cursor_before == "cursor-2"
    assert callable(call.kwargs["ingest_unit"])


@pytest.mark.asyncio
async def test_production_resume_falls_back_to_raw_page_stream_checkpoint():
    from src.application.ingestion.source_unit_resume import resume_quarantined_source_unit

    checkpoint = _checkpoint()
    checkpoint_repo = MagicMock()
    checkpoint_repo.find_by_source_unit_key = AsyncMock(return_value=None)
    checkpoint_repo.find_by_stream = AsyncMock(return_value=checkpoint)
    raw_page_repo = MagicMock()
    raw_page_repo.find_one = AsyncMock(
        return_value=RawIngestionPage(
            stageKey="stage-1",
            partner="MOMO",
            fetchConfigId="fetch-1",
            sourceType="API",
            streamKey=checkpoint.stream_key,
            reconciliationDate=datetime(2026, 8, 26, tzinfo=UTC),
            sourceUnitKey="unit-2",
            page=2,
            cursorBefore="cursor-1",
            cursorAfter="cursor-2",
            localPath="/tmp/page-2.json",
        )
    )
    quarantine_repo = MagicMock()
    quarantine_repo.find_many = AsyncMock(return_value=([], None))
    source_file_repo = MagicMock()
    source_file_repo.find_by_fetch_unit_key = AsyncMock(return_value=None)
    fetch_repo = MagicMock()
    fetch_repo.find_by_id = AsyncMock(return_value=_fetch_config())

    with (
        patch(
            "src.application.ingestion.source_unit_resume.IngestionCheckpointRepository",
            return_value=checkpoint_repo,
        ),
        patch(
            "src.application.ingestion.source_unit_resume.RawIngestionPageRepository",
            return_value=raw_page_repo,
        ),
        patch(
            "src.application.ingestion.source_unit_resume.IngestionQuarantineRepository",
            return_value=quarantine_repo,
        ),
        patch(
            "src.application.ingestion.source_unit_resume.ReconciliationFileRepository",
            return_value=source_file_repo,
        ),
        patch(
            "src.application.ingestion.source_unit_resume.FetchConfigRepository",
            return_value=fetch_repo,
        ),
        patch(
            "src.application.ingestion.source_unit_resume.build_source_unit_ingestor",
            return_value=(AsyncMock(), {}),
        ),
        patch(
            "src.application.ingestion.source_unit_resume.build_config_loader",
            return_value=MagicMock(),
        ),
        patch(
            "src.application.ingestion.source_unit_resume.resume_held_source_unit",
            new=AsyncMock(return_value={"success": True, "processed": 1}),
        ) as resume,
    ):
        result = await resume_quarantined_source_unit(
            object(),
            "unit-2",
            operator_id="operator-1",
            reason="Conflict records resolved",
        )

    assert result == {"success": True, "processed": 1}
    checkpoint_repo.find_by_stream.assert_awaited_once_with(
        partner="MOMO",
        fetch_config_id="fetch-1",
        source_type="API",
        stream_key=checkpoint.stream_key,
        mode=IngestionMode.SCHEDULED,
    )
    assert resume.await_args.kwargs["unit"].source_unit_key == "unit-2"


@pytest.mark.asyncio
async def test_quarantine_api_exposes_source_unit_resume_entry_point():
    from src.api.quarantine import (
        QuarantineSourceUnitResumePayload,
        resume_quarantine_source_unit,
    )

    request = MagicMock()
    request.headers = {"X-Actor": "operator-1"}

    with patch(
        "src.api.quarantine.resume_quarantined_source_unit",
        new=AsyncMock(return_value={"success": True, "processed": 1}),
    ) as resume:
        result = await resume_quarantine_source_unit(
            request,
            "unit-1",
            QuarantineSourceUnitResumePayload(
                actionId="resume-1",
                reason="All conflict records resolved.",
            ),
        )

    assert result == {"success": True, "processed": 1}
    resume.assert_awaited_once_with(
        request.app.state.db,
        "unit-1",
        operator_id="operator-1",
        reason="All conflict records resolved.",
        action_id="resume-1",
        audit_recorder=ANY,
    )


@pytest.mark.asyncio
async def test_resume_reconciles_completed_file_before_consuming_raw_page():
    from src.application.ingestion.source_unit_resume import resume_quarantined_source_unit

    events: list[str] = []
    checkpoint = _checkpoint()
    checkpoint_repo = MagicMock()
    checkpoint_repo.find_by_source_unit_key = AsyncMock(return_value=checkpoint)

    async def claim_unit(**_kwargs):
        events.append("claim")
        return checkpoint, True

    checkpoint_repo.claim_unit = claim_unit
    checkpoint_repo.mark_completed = AsyncMock(
        side_effect=lambda *_args, **_kwargs: events.append("mark_completed") or True
    )
    checkpoint_repo.advance = AsyncMock(
        side_effect=lambda *_args, **_kwargs: events.append("advance") or True
    )

    page = RawIngestionPage(
        stageKey="stage-1",
        partner="MOMO",
        fetchConfigId="fetch-1",
        sourceType="API",
        streamKey=checkpoint.stream_key,
        reconciliationDate=datetime(2026, 8, 26, tzinfo=UTC),
        sourceUnitKey="unit-1",
        page=3,
        cursorBefore="cursor-2",
        cursorAfter="cursor-3",
        localPath="/tmp/page-3.json",
    )
    raw_page_repo = MagicMock()
    raw_page_repo.find_one = AsyncMock(return_value=page)
    raw_page_repo.mark_consumed = AsyncMock(
        side_effect=lambda _key: events.append("consume") or True
    )

    source_file = ReconciliationFile(
        partner="MOMO",
        fileName="page-3.json",
        fileHash="hash-3",
        fileType="SETTLEMENT",
        reconciliationDate=page.reconciliation_date,
        fetchUnitKey="unit-1",
        processingStatus="COMPLETED",
        configVersion="mapping-v1",
    )
    source_file_repo = MagicMock()
    source_file_repo.find_by_fetch_unit_key = AsyncMock(return_value=source_file)
    quarantine_repo = MagicMock()
    quarantine_repo.find_many = AsyncMock(return_value=([], None))
    quarantine_repo.has_unresolved_blockers = AsyncMock(return_value=False)
    fetch_repo = MagicMock()
    fetch_repo.find_by_id = AsyncMock(return_value=_fetch_config())
    reconciliation = SimpleNamespace(
        execute=AsyncMock(side_effect=lambda _command: events.append("reconcile") or [])
    )
    cleanup = AsyncMock(side_effect=lambda _config, _unit: events.append("cleanup"))

    with (
        patch(
            "src.application.ingestion.source_unit_resume.IngestionCheckpointRepository",
            return_value=checkpoint_repo,
        ),
        patch(
            "src.application.ingestion.source_unit_resume.RawIngestionPageRepository",
            return_value=raw_page_repo,
        ),
        patch(
            "src.application.ingestion.source_unit_resume.ReconciliationFileRepository",
            return_value=source_file_repo,
        ),
        patch(
            "src.application.ingestion.source_unit_resume.IngestionQuarantineRepository",
            return_value=quarantine_repo,
        ),
        patch(
            "src.application.ingestion.source_unit_resume.FetchConfigRepository",
            return_value=fetch_repo,
        ),
        patch(
            "src.application.ingestion.source_unit_resume.build_config_loader",
            return_value=MagicMock(),
        ),
        patch(
            "src.application.ingestion.source_unit_resume.build_source_unit_ingestor",
            return_value=(AsyncMock(), {}),
        ),
        patch(
            "src.application.ingestion.source_unit_resume.build_reconciliation_service",
            return_value=reconciliation,
        ),
        patch(
            "src.application.ingestion.source_unit_resume.cleanup_source_unit",
            new=cleanup,
        ),
    ):
        result = await resume_quarantined_source_unit(
            object(),
            "unit-1",
            operator_id="operator-1",
            reason="All conflict records resolved.",
        )

    assert result["success"] is True
    assert events == ["claim", "reconcile", "mark_completed", "advance", "consume", "cleanup"]
    reconciliation.execute.assert_awaited_once()
