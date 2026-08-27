from datetime import UTC, datetime, timedelta

import pytest

from src.domain.ingestion import quarantine
from src.domain.ingestion.quarantine import QuarantineSeverity, QuarantineStatus


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
    priority_model = getattr(quarantine, "QuarantinePriority", None)
    assert priority_model is not None

    record = _record()
    dumped = record.model_dump(by_alias=True)

    assert record.priority is priority_model.NORMAL
    assert dumped.get("priority") == "NORMAL"
    assert record.review_due_at == record.created_at + timedelta(hours=24)
    assert dumped.get("claimedBy") is None
    assert dumped.get("claimedAt") is None
    assert dumped.get("lastAttemptError") is None
    assert dumped.get("lastActionId") is None
    assert dumped.get("escalationLevel") == 0
    assert dumped.get("escalatedAt") is None
    assert dumped.get("escalatedBy") is None
    assert dumped.get("resolutionHistory") == []
    assert dumped.get("retentionUntil") is None


def test_existing_quarantine_documents_read_with_operator_defaults():
    priority_model = getattr(quarantine, "QuarantinePriority", None)
    assert priority_model is not None

    raw = _record().model_dump(by_alias=True)
    for key in (
        "priority",
        "reviewDueAt",
        "escalationLevel",
        "escalatedAt",
        "escalatedBy",
        "lastActionId",
    ):
        raw.pop(key, None)

    record = quarantine.IngestionQuarantineRecord.model_validate(raw)

    assert record.priority is priority_model.NORMAL
    assert record.review_due_at == record.created_at + timedelta(hours=24)
    assert record.escalation_level == 0
    assert record.escalated_at is None
    assert record.escalated_by is None
    assert record.last_action_id is None


def test_conflict_and_fatal_quarantine_records_default_to_high_priority():
    priority_model = getattr(quarantine, "QuarantinePriority", None)
    assert priority_model is not None

    conflict = _record()
    conflict = conflict.model_copy(update={"errors": [{"errorCode": "CONFLICTING_DUPLICATE"}]})
    fatal = _record()
    fatal = fatal.model_copy(update={"severity": QuarantineSeverity.FATAL})

    assert quarantine.IngestionQuarantineRecord.model_validate(
        conflict.model_dump(by_alias=True)
    ).priority is priority_model.HIGH
    assert quarantine.IngestionQuarantineRecord.model_validate(
        fatal.model_dump(by_alias=True)
    ).priority is priority_model.HIGH


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
        actionId="action-1",
        outcome="CLAIMED",
        metadata={"source": "test"},
    )

    record.resolution_history.append(event)

    assert event.model_dump(by_alias=True)["fromStatus"] == "PENDING"
    assert event.model_dump(by_alias=True)["toStatus"] == "REPROCESSING"
    assert event.model_dump(by_alias=True)["actionId"] == "action-1"
    assert event.model_dump(by_alias=True)["outcome"] == "CLAIMED"
    assert record.raw_row == raw_row
    assert record.errors == errors
