"""TDD contracts for safe resume of a held source unit."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.domain.ingestion.checkpoints import (
    CheckpointStatus,
    IngestionCheckpoint,
    IngestionMode,
)
from src.domain.ingestion.source_units import SourceUnitMetadata


def _unit() -> SourceUnitMetadata:
    return SourceUnitMetadata(
        sourceUnitKey="unit-1",
        page=1,
        cursorBefore="cursor-0",
        cursorAfter="cursor-1",
        localPath="/tmp/unit-1.json",
    )


def _checkpoint(*, completed: bool = False) -> IngestionCheckpoint:
    return IngestionCheckpoint(
        partner="MOMO",
        fetchConfigId="fetch-1",
        sourceType="API",
        streamKey="MOMO:daily",
        mode=IngestionMode.SCHEDULED,
        status=CheckpointStatus.COMPLETED if completed else CheckpointStatus.PROCESSING,
        lastCompletedUnitKey="unit-1" if completed else None,
        currentUnitKey=None if completed else "unit-1",
        claimId=None if completed else "claim-1",
    )


class _CheckpointRepo:
    def __init__(self, events, *, completed: bool = False):
        self.events = events
        self.checkpoint = _checkpoint(completed=completed)

    async def claim_unit(self, **_kwargs):
        self.events.append("claim")
        if self.checkpoint.last_completed_unit_key == "unit-1":
            return self.checkpoint, False
        return self.checkpoint, True

    async def mark_completed(self, *_args, **_kwargs):
        self.events.append("mark_completed")
        return True

    async def advance(self, *_args, **_kwargs):
        self.events.append("advance")
        return True

    async def mark_failed(self, *_args, **_kwargs):
        self.events.append("mark_failed")
        return True


def _identity() -> dict:
    return {
        "partner": "MOMO",
        "fetchConfigId": "fetch-1",
        "sourceType": "API",
        "streamKey": "MOMO:daily",
        "lastCompletedUnitKey": None,
        "configVersion": "mapping-v1",
        "sourceEndpoint": "/settlements",
    }


@pytest.mark.asyncio
async def test_unresolved_conflict_refuses_resume_before_claim():
    from src.application.automation.stream_ingestion import resume_held_source_unit

    checkpoint_repo = _CheckpointRepo([])
    quarantine_repo = SimpleNamespace(has_unresolved_blockers=AsyncMock(return_value=True))
    ingest = AsyncMock()

    result = await resume_held_source_unit(
        source_unit_key="unit-1",
        quarantine_repo=quarantine_repo,
        checkpoint_repo=checkpoint_repo,
        stream_identity=_identity(),
        unit=_unit(),
        ingest_unit=ingest,
    )

    assert result["success"] is False
    assert result["outcome"] == "QUARANTINE_BLOCKED"
    assert checkpoint_repo.events == []
    ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_successful_resume_advances_then_consumes_and_cleans_up():
    from src.application.automation.paginated_stream_runner import (
        resume_paginated_source_unit,
    )

    events: list[str] = []
    checkpoint_repo = _CheckpointRepo(events)
    quarantine_repo = SimpleNamespace(has_unresolved_blockers=AsyncMock(return_value=False))
    raw_page_repo = SimpleNamespace(
        mark_consumed=AsyncMock(side_effect=lambda _key: events.append("consume"))
    )
    cleanup = AsyncMock(side_effect=lambda _unit: events.append("cleanup"))
    context = SimpleNamespace(
        checkpoint_repo=checkpoint_repo,
        checkpoint=checkpoint_repo.checkpoint,
        raw_page_repo=raw_page_repo,
        stage_key="stage-1",
        cleanup_unit=cleanup,
        mode=IngestionMode.SCHEDULED,
        retry_policy=None,
        identity=_identity(),
        dependencies=SimpleNamespace(),
    )

    async def ingest(unit):
        events.append("ingest")
        return {"success": True, "outcome": "INGESTED"}

    result = await resume_paginated_source_unit(
        context=context,
        quarantine_repo=quarantine_repo,
        unit=_unit(),
        ingest_unit=ingest,
    )

    assert result["success"] is True
    assert events == ["claim", "ingest", "mark_completed", "advance", "consume", "cleanup"]


@pytest.mark.asyncio
async def test_replay_failure_does_not_advance_or_consume_raw_page():
    from src.application.automation.stream_ingestion import resume_held_source_unit

    events: list[str] = []
    checkpoint_repo = _CheckpointRepo(events)
    quarantine_repo = SimpleNamespace(has_unresolved_blockers=AsyncMock(return_value=False))
    cleanup = AsyncMock(side_effect=lambda _unit: events.append("cleanup"))

    result = await resume_held_source_unit(
        source_unit_key="unit-1",
        quarantine_repo=quarantine_repo,
        checkpoint_repo=checkpoint_repo,
        stream_identity=_identity(),
        unit=_unit(),
        ingest_unit=AsyncMock(
            return_value={
                "success": False,
                "error": "source row still invalid",
                "errorCode": "INVALID_AMOUNT",
                "retryable": False,
            }
        ),
        on_unit_completed=cleanup,
    )

    assert result["success"] is False
    assert "mark_failed" in events
    assert "mark_completed" not in events
    assert "advance" not in events
    cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_second_resume_trigger_is_replay_safe():
    from src.application.automation.stream_ingestion import resume_held_source_unit

    events: list[str] = []
    checkpoint_repo = _CheckpointRepo(events, completed=True)
    quarantine_repo = SimpleNamespace(has_unresolved_blockers=AsyncMock(return_value=False))
    ingest = AsyncMock()

    result = await resume_held_source_unit(
        source_unit_key="unit-1",
        quarantine_repo=quarantine_repo,
        checkpoint_repo=checkpoint_repo,
        stream_identity=_identity(),
        unit=_unit(),
        ingest_unit=ingest,
    )

    assert result["success"] is True
    assert result["replayed"] == 1
    ingest.assert_not_awaited()
