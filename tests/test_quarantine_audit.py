"""TDD contracts for quarantine audit events and bounded counters."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.ingestion.quarantine import (
    IngestionQuarantineRecord,
    QuarantinePhase,
    QuarantineStatus,
)
from src.domain.partner_transaction.duplicates import BatchWriteResult


def _record() -> IngestionQuarantineRecord:
    return IngestionQuarantineRecord(
        sourceFileId="file-1",
        sourceUnitKey="unit-1",
        partner="MOMO",
        reconciliationDate=datetime(2026, 8, 1, tzinfo=UTC),
        rowNumber=7,
        rawRow={"id": "TX-007", "secret": "[REDACTED]"},
        errors=[{"errorCode": "INVALID_AMOUNT"}],
        phase=QuarantinePhase.VALIDATION,
    )


def _repo(record):
    repo = MagicMock()
    claimed = record.model_copy(
        update={
            "status": QuarantineStatus.REPROCESSING,
            "claimed_by": "operator-1",
            "attempt_count": 2,
        }
    )
    repo.find_action = AsyncMock(return_value=None)
    repo.find_by_id = AsyncMock(side_effect=[record, claimed])
    repo.claim = AsyncMock(
        return_value=claimed
    )
    repo.resolve = AsyncMock(return_value=True)
    repo.release_for_retry = AsyncMock(return_value=True)
    return repo


def _request(mode: str):
    from src.application.ingestion.quarantine_reprocessing import QuarantineReprocessRequest

    return QuarantineReprocessRequest(
        recordId="record-1",
        operatorId="operator-1",
        actionId="action-1",
        expectedStatus=QuarantineStatus.PENDING,
        mode=mode,
        reason="operator decision",
    )


@pytest.mark.asyncio
async def test_reprocess_emits_claim_and_reprocessed_audits_without_sensitive_payload():
    from src.application.ingestion.quarantine_reprocessing import QuarantineReprocessMode
    from src.application.ingestion.quarantine_service import QuarantineResolutionService

    audit = AsyncMock()
    service = QuarantineResolutionService(
        _repo(_record()),
        SimpleNamespace(read_row=AsyncMock(return_value=("TX-007", "100"))),
        SimpleNamespace(read_row=AsyncMock()),
        row_processor=SimpleNamespace(
            process=MagicMock(
                return_value=SimpleNamespace(is_valid=True, data_container={"id": "TX-007"})
            )
        ),
        persist_row=AsyncMock(return_value=BatchWriteResult(inserted=1)),
        audit_recorder=audit,
    )

    result = await service.resolve(_request(QuarantineReprocessMode.REPLAY_SOURCE_ROW))

    assert result.success is True
    assert result.quality_counters["inputRows"] == 1
    assert result.quality_counters["persistedRows"] == 1
    assert result.quality_counters["quarantinedRows"] == 0
    actions = [call.kwargs["action"] for call in audit.await_args_list]
    assert actions == ["QUARANTINE_CLAIMED", "QUARANTINE_REPROCESSED"]
    metadata = audit.await_args_list[0].kwargs["metadata"]
    assert {
        "recordId",
        "partner",
        "sourceFileId",
        "sourceUnitKey",
        "errorCode",
        "attempt",
        "actor",
        "reason",
    } <= metadata.keys()
    assert "rawRow" not in str(metadata)
    assert "fingerprint" not in str(metadata).lower()


@pytest.mark.asyncio
async def test_retryable_failure_emits_retry_scheduled_and_classification():
    from src.application.ingestion.quarantine_reprocessing import QuarantineReprocessMode
    from src.application.ingestion.quarantine_service import QuarantineResolutionService

    audit = AsyncMock()
    service = QuarantineResolutionService(
        _repo(_record()),
        SimpleNamespace(read_row=AsyncMock(return_value=("TX-007", "100"))),
        SimpleNamespace(read_row=AsyncMock()),
        row_processor=SimpleNamespace(
            process=MagicMock(
                return_value=SimpleNamespace(is_valid=True, data_container={"id": "TX-007"})
            )
        ),
        persist_row=AsyncMock(side_effect=RuntimeError("database unavailable")),
        audit_recorder=audit,
    )

    result = await service.resolve(_request(QuarantineReprocessMode.REPLAY_SOURCE_ROW))

    assert result.outcome == "RETRYABLE_FAILURE"
    assert result.failure_classification == "RETRYABLE_INFRASTRUCTURE"
    assert [call.kwargs["action"] for call in audit.await_args_list] == [
        "QUARANTINE_CLAIMED",
        "QUARANTINE_RETRY_SCHEDULED",
    ]


@pytest.mark.asyncio
async def test_terminal_rejection_is_distinct_from_retryable_failure():
    from src.application.ingestion.quarantine_reprocessing import QuarantineReprocessMode
    from src.application.ingestion.quarantine_service import QuarantineResolutionService

    audit = AsyncMock()
    service = QuarantineResolutionService(
        _repo(_record()),
        SimpleNamespace(read_row=AsyncMock()),
        SimpleNamespace(read_row=AsyncMock()),
        audit_recorder=audit,
    )

    result = await service.resolve(_request(QuarantineReprocessMode.REJECT))

    assert result.status is QuarantineStatus.REJECTED
    assert result.failure_classification == "TERMINAL_OPERATOR_REJECTION"
    assert [call.kwargs["action"] for call in audit.await_args_list] == [
        "QUARANTINE_CLAIMED",
        "QUARANTINE_REJECTED",
    ]


def test_quarantine_counters_reuse_ingestion_row_accounting_names():
    from src.application.ingestion.contracts import serialize_quarantine_counters

    counters = serialize_quarantine_counters(
        input_rows=1,
        persisted_rows=0,
        rejected_rows=1,
        duplicate_rows=0,
        failed_rows=0,
        quarantined_rows=0,
    )

    assert counters == {
        "inputRows": 1,
        "persistedRows": 0,
        "rejectedRows": 1,
        "duplicateRows": 0,
        "failedRows": 0,
        "persistenceFailedRows": 0,
        "quarantinedRows": 0,
    }
