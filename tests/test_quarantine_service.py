"""TDD contracts for single-record quarantine resolution."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.ingestion.quarantine import (
    IngestionQuarantineRecord,
    QuarantineAction,
    QuarantinePhase,
    QuarantineStatus,
)
from src.domain.ingestion.quality import QualityRuleCode
from src.domain.partner_transaction.duplicates import BatchWriteResult, DuplicateDetail


def _record(**overrides) -> IngestionQuarantineRecord:
    payload = {
        "sourceFileId": "file-1",
        "sourceUnitKey": "unit-1",
        "partner": "MOMO",
        "reconciliationDate": datetime(2026, 8, 1, tzinfo=UTC),
        "rowNumber": 7,
        "rawRow": ("TX-007", "100"),
        "phase": QuarantinePhase.VALIDATION,
        "existingFingerprint": "existing-fingerprint",
    }
    payload.update(overrides)
    return IngestionQuarantineRecord(**payload)


def _claimed(record: IngestionQuarantineRecord) -> IngestionQuarantineRecord:
    return record.model_copy(
        update={
            "status": QuarantineStatus.REPROCESSING,
            "claimed_by": "operator-1",
            "attempt_count": 2,
        }
    )


def _repo(record: IngestionQuarantineRecord):
    repo = MagicMock()
    repo.claim = AsyncMock(return_value=_claimed(record))
    repo.resolve = AsyncMock(return_value=True)
    repo.release_for_retry = AsyncMock(return_value=True)
    return repo


def _request(mode: str, **overrides):
    from src.application.ingestion.quarantine_reprocessing import QuarantineReprocessRequest

    payload = {
        "recordId": "record-1",
        "operatorId": "operator-1",
        "mode": mode,
    }
    payload.update(overrides)
    return QuarantineReprocessRequest(**payload)


@pytest.mark.asyncio
async def test_reprocess_persists_then_resolves():
    from src.application.ingestion.quarantine_reprocessing import QuarantineReprocessMode
    from src.application.ingestion.quarantine_service import QuarantineResolutionService

    record = _record()
    repo = _repo(record)
    source_repo = SimpleNamespace(read_row=AsyncMock(return_value={"id": "TX-007"}))
    raw_repo = SimpleNamespace(read_row=AsyncMock())
    processor = SimpleNamespace(
        process=MagicMock(
            return_value=SimpleNamespace(
                is_valid=True,
                data_container={"id": "TX-007"},
                errors=[],
            )
        )
    )
    persist = AsyncMock(return_value=BatchWriteResult(inserted=1))
    service = QuarantineResolutionService(
        repo,
        source_repo,
        raw_repo,
        row_processor=processor,
        persist_row=persist,
    )

    result = await service.resolve(_request(QuarantineReprocessMode.REPLAY_SOURCE_ROW))

    assert result.success is True
    assert result.status is QuarantineStatus.RESOLVED
    assert result.outcome == "RESOLVED"
    persist.assert_awaited_once_with({"id": "TX-007"})
    repo.resolve.assert_awaited_once_with(
        "record-1",
        QuarantineStatus.RESOLVED,
        "operator-1",
        QuarantineAction.REPROCESS,
        "Quarantine row reprocessed successfully.",
        {"origin": "AUTHORITATIVE_SOURCE_FILE", "mappingVersion": None},
    )


@pytest.mark.asyncio
async def test_equivalent_reprocess_is_resolved_without_conflict():
    from src.application.ingestion.quarantine_reprocessing import QuarantineReprocessMode
    from src.application.ingestion.quarantine_service import QuarantineResolutionService

    detail = DuplicateDetail(
        identify="MOMO",
        ingestion_key="TX-007",
        duplicate_type=QualityRuleCode.EQUIVALENT_DUPLICATE,
        incoming_index=0,
        incoming_fingerprint="same",
        existing_fingerprint="same",
    )
    repo = _repo(_record())
    service = QuarantineResolutionService(
        repo,
        SimpleNamespace(read_row=AsyncMock(return_value=("TX-007", "100"))),
        SimpleNamespace(read_row=AsyncMock()),
        row_processor=SimpleNamespace(
            process=MagicMock(
                return_value=SimpleNamespace(is_valid=True, data_container={"id": "TX-007"})
            )
        ),
        persist_row=AsyncMock(
            return_value=BatchWriteResult(
                inserted=0,
                duplicates=1,
                equivalent_duplicates=1,
                duplicate_details=[detail],
            )
        ),
    )

    result = await service.resolve(_request(QuarantineReprocessMode.REPLAY_SOURCE_ROW))

    assert result.success is True
    assert result.outcome == "EQUIVALENT_DUPLICATE"
    assert repo.resolve.await_args.args[3] is QuarantineAction.REPROCESS


@pytest.mark.asyncio
async def test_conflict_still_present_returns_record_to_pending():
    from src.application.ingestion.quarantine_reprocessing import QuarantineReprocessMode
    from src.application.ingestion.quarantine_service import QuarantineResolutionService

    detail = DuplicateDetail(
        identify="MOMO",
        ingestion_key="TX-007",
        duplicate_type=QualityRuleCode.CONFLICTING_DUPLICATE,
        incoming_index=0,
        incoming_fingerprint="new",
        existing_fingerprint="old",
    )
    repo = _repo(_record())
    service = QuarantineResolutionService(
        repo,
        SimpleNamespace(read_row=AsyncMock(return_value=("TX-007", "999"))),
        SimpleNamespace(read_row=AsyncMock()),
        row_processor=SimpleNamespace(
            process=MagicMock(
                return_value=SimpleNamespace(is_valid=True, data_container={"id": "TX-007"})
            )
        ),
        persist_row=AsyncMock(
            return_value=BatchWriteResult(
                inserted=0,
                duplicates=1,
                conflicting_duplicates=1,
                duplicate_details=[detail],
            )
        ),
    )

    result = await service.resolve(_request(QuarantineReprocessMode.REPLAY_SOURCE_ROW))

    assert result.success is False
    assert result.status is QuarantineStatus.PENDING
    assert result.outcome == "CONFLICT_REMAINS"
    repo.release_for_retry.assert_awaited_once()


@pytest.mark.asyncio
async def test_accept_existing_requires_matching_fingerprint():
    from src.application.ingestion.quarantine_reprocessing import QuarantineReprocessMode
    from src.application.ingestion.quarantine_service import QuarantineResolutionService

    repo = _repo(_record())
    service = QuarantineResolutionService(
        repo,
        SimpleNamespace(read_row=AsyncMock()),
        SimpleNamespace(read_row=AsyncMock()),
        existing_fingerprint_reader=AsyncMock(return_value="different"),
    )

    result = await service.resolve(_request(QuarantineReprocessMode.ACCEPT_EXISTING))

    assert result.success is False
    assert result.status is QuarantineStatus.PENDING
    assert result.outcome == "FINGERPRINT_MISMATCH"
    repo.resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_reject_is_terminal_and_keeps_record():
    from src.application.ingestion.quarantine_reprocessing import QuarantineReprocessMode
    from src.application.ingestion.quarantine_service import QuarantineResolutionService

    repo = _repo(_record())
    service = QuarantineResolutionService(
        repo,
        SimpleNamespace(read_row=AsyncMock()),
        SimpleNamespace(read_row=AsyncMock()),
    )

    result = await service.resolve(
        _request(QuarantineReprocessMode.REJECT, reason="Confirmed invalid settlement row.")
    )

    assert result.success is True
    assert result.status is QuarantineStatus.REJECTED
    repo.resolve.assert_awaited_once_with(
        "record-1",
        QuarantineStatus.REJECTED,
        "operator-1",
        QuarantineAction.REJECT,
        "Confirmed invalid settlement row.",
        {},
    )


@pytest.mark.asyncio
async def test_concurrent_claim_loss_does_not_process_row():
    from src.application.ingestion.quarantine_reprocessing import QuarantineReprocessMode
    from src.application.ingestion.quarantine_service import QuarantineResolutionService

    repo = _repo(_record())
    repo.claim = AsyncMock(return_value=None)
    persist = AsyncMock()
    service = QuarantineResolutionService(
        repo,
        SimpleNamespace(read_row=AsyncMock()),
        SimpleNamespace(read_row=AsyncMock()),
        row_processor=SimpleNamespace(process=MagicMock()),
        persist_row=persist,
    )

    result = await service.resolve(_request(QuarantineReprocessMode.REPLAY_SOURCE_ROW))

    assert result.success is False
    assert result.outcome == "CLAIM_NOT_ACQUIRED"
    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_retryable_persistence_failure_releases_claim():
    from src.application.ingestion.quarantine_reprocessing import QuarantineReprocessMode
    from src.application.ingestion.quarantine_service import QuarantineResolutionService

    repo = _repo(_record())
    service = QuarantineResolutionService(
        repo,
        SimpleNamespace(read_row=AsyncMock(return_value=("TX-007", "100"))),
        SimpleNamespace(read_row=AsyncMock()),
        row_processor=SimpleNamespace(
            process=MagicMock(
                return_value=SimpleNamespace(is_valid=True, data_container={"id": "TX-007"})
            )
        ),
        persist_row=AsyncMock(side_effect=RuntimeError("database unavailable")),
    )

    result = await service.resolve(_request(QuarantineReprocessMode.REPLAY_SOURCE_ROW))

    assert result.success is False
    assert result.status is QuarantineStatus.PENDING
    assert result.outcome == "RETRYABLE_FAILURE"
    repo.release_for_retry.assert_awaited_once()
