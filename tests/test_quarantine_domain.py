from datetime import UTC, datetime

import pytest

from src.domain.ingestion import quarantine
from src.domain.ingestion.quarantine import QuarantineStatus


def _record():
    return quarantine.IngestionQuarantineRecord(
        sourceFileId="file-1",
        sourceUnitKey="unit-1",
        partner="MOMO",
        reconciliationDate=datetime(2026, 8, 26, tzinfo=UTC),
        rowNumber=2,
        rawRow={"id": "tx-1", "amount": "10.00"},
        errors=[{"errorCode": "INVALID_AMOUNT"}],
    )


def test_pending_can_be_claimed_for_reprocessing():
    transition = getattr(quarantine, "assert_quarantine_transition", None)

    assert transition is not None
    transition(QuarantineStatus.PENDING, QuarantineStatus.REPROCESSING)


@pytest.mark.parametrize(
    "target",
    [QuarantineStatus.PENDING, QuarantineStatus.RESOLVED, QuarantineStatus.REJECTED],
)
def test_pending_cannot_jump_to_resolution(target):
    transition = getattr(quarantine, "assert_quarantine_transition", None)

    assert transition is not None
    with pytest.raises(ValueError):
        transition(QuarantineStatus.PENDING, target)


def test_terminal_quarantine_status_cannot_transition_again():
    transition = getattr(quarantine, "assert_quarantine_transition", None)

    assert transition is not None
    with pytest.raises(ValueError):
        transition(QuarantineStatus.RESOLVED, QuarantineStatus.REPROCESSING)


def test_quarantine_record_has_claim_history_and_retention_defaults():
    record = _record()
    dumped = record.model_dump(by_alias=True)

    assert dumped.get("claimedBy") is None
    assert dumped.get("claimedAt") is None
    assert dumped.get("lastAttemptError") is None
    assert dumped.get("resolutionHistory") == []
    assert dumped.get("retentionUntil") is None


def test_resolution_event_uses_stable_aliases_without_mutating_evidence():
    event_model = getattr(quarantine, "QuarantineResolutionEvent", None)
    assert event_model is not None

    record = _record()
    raw_row = record.raw_row.copy()
    errors = list(record.errors)
    event = event_model(
        fromStatus=QuarantineStatus.PENDING,
        toStatus=QuarantineStatus.REPROCESSING,
        action=quarantine.QuarantineAction.REPROCESS,
        actor="operator-1",
        reason="Retry after correcting source data.",
        attempt=1,
        metadata={"source": "test"},
    )

    record.resolution_history.append(event)

    assert event.model_dump(by_alias=True)["fromStatus"] == "PENDING"
    assert event.model_dump(by_alias=True)["toStatus"] == "REPROCESSING"
    assert record.raw_row == raw_row
    assert record.errors == errors
