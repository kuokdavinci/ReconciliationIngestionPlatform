"""Explicit operator action contracts for quarantine resolution."""

import asyncio
from datetime import UTC, datetime
from inspect import signature
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.ingestion.quarantine_reprocessing import (
    QuarantineReprocessMode,
    QuarantineReprocessRequest,
)
from src.application.ingestion.quarantine_service import QuarantineResolutionService
from src.domain.ingestion.quarantine import (
    IngestionQuarantineRecord,
    QuarantineAction,
    QuarantinePhase,
    QuarantineResolutionEvent,
    QuarantineStatus,
)


def _record(status=QuarantineStatus.PENDING, **overrides):
    payload = {
        "sourceFileId": "file-1",
        "sourceUnitKey": "unit-1",
        "partner": "MOMO",
        "reconciliationDate": datetime(2026, 8, 1, tzinfo=UTC),
        "rowNumber": 7,
        "rawRow": {"id": "TX-007"},
        "phase": QuarantinePhase.VALIDATION,
        "status": status,
        "claimedBy": "operator-1" if status is QuarantineStatus.REPROCESSING else None,
        "attemptCount": 2 if status is QuarantineStatus.REPROCESSING else 1,
    }
    payload.update(overrides)
    return IngestionQuarantineRecord(**payload)


def _repo(record):
    repo = MagicMock()
    repo.find_action = AsyncMock(return_value=None)
    repo.find_by_id = AsyncMock(return_value=record)
    repo.claim = AsyncMock(return_value=record.model_copy(update={
        "status": QuarantineStatus.REPROCESSING,
        "claimed_by": "operator-1",
        "attempt_count": 2,
    }))
    repo.release_for_retry = AsyncMock(return_value=True)
    repo.resolve = AsyncMock(return_value=True)
    repo.escalate = AsyncMock(return_value=record)
    return repo


def _request(mode, **overrides):
    payload = {
        "recordId": "record-1",
        "operatorId": "operator-1",
        "actionId": "action-1",
        "expectedStatus": QuarantineStatus.REPROCESSING,
        "mode": mode,
    }
    payload.update(overrides)
    return QuarantineReprocessRequest(**payload)


def test_operator_action_requires_action_id_and_expected_status():
    with pytest.raises(ValueError):
        QuarantineReprocessRequest(
            recordId="record-1",
            operatorId="operator-1",
            mode=QuarantineReprocessMode.REPLAY_SOURCE_ROW,
        )


def test_quarantine_repository_port_declares_operator_action_contract():
    from src.domain.ingestion.ports import IngestionQuarantineRepositoryPort

    for method_name in ("claim", "release_for_retry", "resolve", "escalate"):
        assert hasattr(IngestionQuarantineRepositoryPort, method_name)
        assert "action_id" in signature(
            getattr(IngestionQuarantineRepositoryPort, method_name)
        ).parameters
    assert hasattr(IngestionQuarantineRepositoryPort, "find_action")
    assert hasattr(IngestionQuarantineRepositoryPort, "summarize")
    assert hasattr(IngestionQuarantineRepositoryPort, "reclaim_expired_claim")
    assert hasattr(IngestionQuarantineRepositoryPort, "reserve_action")


@pytest.mark.asyncio
async def test_claim_is_explicit_and_records_action_id():
    record = _record()
    repo = _repo(record)
    service = QuarantineResolutionService(repo, MagicMock(), MagicMock())

    result = await service.claim(
        "record-1", "operator-1", "claim-1", QuarantineStatus.PENDING
    )

    assert result.success is True
    assert result.outcome == "CLAIMED"
    assert result.action_id == "claim-1"
    assert result.previous_status is QuarantineStatus.PENDING
    assert result.status is QuarantineStatus.REPROCESSING
    repo.claim.assert_awaited_once_with("record-1", "operator-1", action_id="claim-1")


@pytest.mark.asyncio
async def test_resolve_claimed_reprocesses_without_auto_claim():
    record = _record(QuarantineStatus.REPROCESSING)
    repo = _repo(record)
    persist = AsyncMock(return_value=SimpleNamespace(conflicting_duplicates=0, equivalent_duplicates=0, failed=0))
    service = QuarantineResolutionService(
        repo,
        SimpleNamespace(read_row=AsyncMock(return_value={"id": "TX-007"})),
        SimpleNamespace(read_row=AsyncMock()),
        row_processor=SimpleNamespace(
            process=MagicMock(return_value=SimpleNamespace(
                is_valid=True, data_container={"id": "TX-007"}, errors=[]
            ))
        ),
        persist_row=persist,
    )

    result = await service.resolve_claimed(_request(QuarantineReprocessMode.REPLAY_SOURCE_ROW))

    assert result.success is True
    assert result.status is QuarantineStatus.RESOLVED
    assert result.action_id == "action-1"
    repo.claim.assert_not_awaited()
    repo.resolve.assert_awaited_once()
    assert repo.resolve.await_args.kwargs["action_id"] == "action-1"
    assert persist.await_count == 1


@pytest.mark.asyncio
async def test_reject_requires_non_empty_reason():
    record = _record(QuarantineStatus.REPROCESSING)
    service = QuarantineResolutionService(_repo(record), MagicMock(), MagicMock())

    result = await service.resolve_claimed(
        _request(QuarantineReprocessMode.REJECT, reason=" ")
    )

    assert result.outcome == "REASON_REQUIRED"


@pytest.mark.asyncio
async def test_expired_claim_cannot_be_resolved_by_previous_owner():
    record = _record(
        QuarantineStatus.REPROCESSING,
        claimExpiresAt=datetime(2026, 8, 26, tzinfo=UTC),
    )
    repo = _repo(record)
    service = QuarantineResolutionService(
        repo,
        SimpleNamespace(read_row=AsyncMock(return_value={"id": "TX-007"})),
        SimpleNamespace(read_row=AsyncMock()),
        row_processor=SimpleNamespace(
            process=MagicMock(
                return_value=SimpleNamespace(
                    is_valid=True,
                    data_container={"id": "TX-007"},
                    errors=[],
                )
            )
        ),
        persist_row=AsyncMock(),
    )

    result = await service.resolve_claimed(
        _request(QuarantineReprocessMode.REPLAY_SOURCE_ROW)
    )

    assert result.success is False
    assert result.outcome == "CLAIM_EXPIRED"
    repo.release_for_retry.assert_not_awaited()
    repo.resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_claim_is_reclaimed_before_new_claim():
    record = _record(
        QuarantineStatus.REPROCESSING,
        claimExpiresAt=datetime(2026, 8, 26, tzinfo=UTC),
    )
    repo = _repo(record)
    repo.reclaim_expired_claim = AsyncMock(
        return_value=record.model_copy(
            update={
                "status": QuarantineStatus.PENDING,
                "claimed_by": None,
                "claim_expires_at": None,
            }
        )
    )
    service = QuarantineResolutionService(repo, MagicMock(), MagicMock())

    result = await service.claim(
        "record-1", "operator-2", "claim-2", QuarantineStatus.PENDING
    )

    assert result.success is True
    assert result.outcome == "CLAIMED"
    repo.reclaim_expired_claim.assert_awaited_once_with("record-1")


@pytest.mark.asyncio
async def test_missing_source_is_bounded_and_does_not_expose_source_details():
    record = _record(QuarantineStatus.REPROCESSING, rawRow={"secret": "[REDACTED]"})
    service = QuarantineResolutionService(
        _repo(record),
        SimpleNamespace(read_row=AsyncMock(return_value=None)),
        SimpleNamespace(read_row=AsyncMock(return_value=None)),
    )

    result = await service.resolve_claimed(
        _request(QuarantineReprocessMode.REPLAY_SOURCE_ROW)
    )

    assert result.outcome == "SOURCE_EVIDENCE_UNAVAILABLE"
    assert result.quality_counters["persistedRows"] == 0
    assert result.quality_counters["failedRows"] == 1
    assert "file-1" not in (result.reason or "")
    assert "[REDACTED]" not in (result.reason or "")


@pytest.mark.asyncio
async def test_repeated_action_returns_recorded_result_without_persisting_again():
    record = _record(QuarantineStatus.REPROCESSING)
    event = QuarantineResolutionEvent(
        fromStatus=QuarantineStatus.REPROCESSING,
        toStatus=QuarantineStatus.RESOLVED,
        action=QuarantineAction.REPROCESS,
        actor="operator-1",
        reason="resolved",
        attempt=2,
        actionId="action-1",
        outcome="RESOLVED",
    )
    repo = _repo(record)
    repo.find_action = AsyncMock(return_value=event)
    persist = AsyncMock()
    service = QuarantineResolutionService(
        repo,
        MagicMock(),
        MagicMock(),
        persist_row=persist,
    )

    result = await service.resolve_claimed(_request(QuarantineReprocessMode.REPLAY_SOURCE_ROW))

    assert result.success is True
    assert result.outcome == "RESOLVED"
    persist.assert_not_awaited()
    repo.resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_reusing_action_id_for_another_actor_is_a_conflict():
    record = _record(QuarantineStatus.REPROCESSING)
    event = QuarantineResolutionEvent(
        fromStatus=QuarantineStatus.PENDING,
        toStatus=QuarantineStatus.REPROCESSING,
        action=QuarantineAction.REPROCESS,
        actor="other-operator",
        reason="claimed",
        attempt=2,
        actionId="action-1",
        outcome="CLAIMED",
    )
    repo = _repo(record)
    repo.find_action = AsyncMock(return_value=event)
    service = QuarantineResolutionService(repo, MagicMock(), MagicMock())

    result = await service.resolve_claimed(_request(QuarantineReprocessMode.REPLAY_SOURCE_ROW))

    assert result.success is False
    assert result.outcome == "ACTION_ID_REUSE_CONFLICT"
    repo.resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_replay_of_same_action_persists_once():
    record = _record(QuarantineStatus.REPROCESSING)
    repo = _repo(record)
    completed_event = None

    async def find_action(record_id, action_id):
        del record_id, action_id
        return completed_event

    async def persist(_data):
        persist.calls += 1
        await asyncio.sleep(0)
        return SimpleNamespace(conflicting_duplicates=0, equivalent_duplicates=0, failed=0)

    persist.calls = 0

    async def resolve(*_args, **_kwargs):
        nonlocal completed_event
        completed_event = QuarantineResolutionEvent(
            fromStatus=QuarantineStatus.REPROCESSING,
            toStatus=QuarantineStatus.RESOLVED,
            action=QuarantineAction.REPROCESS,
            actor="operator-1",
            reason="resolved",
            attempt=2,
            actionId="action-1",
            outcome="RESOLVED",
        )
        return True

    repo.find_action = find_action
    repo.resolve = resolve
    service = QuarantineResolutionService(
        repo,
        SimpleNamespace(read_row=AsyncMock(return_value={"id": "TX-007"})),
        SimpleNamespace(read_row=AsyncMock()),
        row_processor=SimpleNamespace(
            process=MagicMock(
                return_value=SimpleNamespace(
                    is_valid=True,
                    data_container={"id": "TX-007"},
                    errors=[],
                )
            )
        ),
        persist_row=persist,
    )

    first, second = await asyncio.gather(
        service.resolve_claimed(_request(QuarantineReprocessMode.REPLAY_SOURCE_ROW)),
        service.resolve_claimed(_request(QuarantineReprocessMode.REPLAY_SOURCE_ROW)),
    )

    assert persist.calls == 1
    assert {first.outcome, second.outcome} == {"RESOLVED"}


@pytest.mark.asyncio
async def test_document_reservation_blocks_replay_before_persistence():
    record = _record(QuarantineStatus.REPROCESSING)
    repo = _repo(record)
    repo.reserve_action = AsyncMock(return_value="IN_PROGRESS")
    persist = AsyncMock()
    service = QuarantineResolutionService(
        repo,
        SimpleNamespace(read_row=AsyncMock(return_value={"id": "TX-007"})),
        SimpleNamespace(read_row=AsyncMock()),
        row_processor=SimpleNamespace(
            process=MagicMock(
                return_value=SimpleNamespace(
                    is_valid=True,
                    data_container={"id": "TX-007"},
                    errors=[],
                )
            )
        ),
        persist_row=persist,
    )

    result = await service.resolve_claimed(
        _request(QuarantineReprocessMode.REPLAY_SOURCE_ROW)
    )

    assert result.success is False
    assert result.outcome == "ACTION_IN_PROGRESS"
    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_escalate_preserves_status_and_uses_repository_action():
    record = _record(QuarantineStatus.REPROCESSING)
    repo = _repo(record)
    service = QuarantineResolutionService(repo, MagicMock(), MagicMock())

    result = await service.escalate(
        "record-1", "operator-1", "escalate-1", QuarantineStatus.REPROCESSING, "Needs review"
    )

    assert result.success is True
    assert result.outcome == "ESCALATED"
    repo.escalate.assert_awaited_once_with(
        "record-1", "operator-1", "escalate-1", QuarantineStatus.REPROCESSING, "Needs review"
    )
