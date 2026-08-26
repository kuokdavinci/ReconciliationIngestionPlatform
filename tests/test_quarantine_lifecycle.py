"""End-to-end contract for the Workstream D quarantine lifecycle."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.ingestion.quarantine_reprocessing import (
    QuarantineReprocessMode,
    QuarantineReprocessRequest,
)
from src.application.ingestion.quarantine_service import QuarantineResolutionService
from src.application.ingestion.source_unit_orchestrator import resume_held_source_unit
from src.domain.ingestion.checkpoints import (
    CheckpointStatus,
    IngestionCheckpoint,
    IngestionMode,
)
from src.domain.ingestion.quarantine import (
    IngestionQuarantineRecord,
    QuarantineAction,
    QuarantinePhase,
    QuarantineResolutionEvent,
    QuarantineStatus,
)
from src.domain.ingestion.source_units import SourceUnitMetadata
from src.domain.partner_transaction.duplicates import BatchWriteResult, DuplicateDetail
from src.domain.ingestion.quality import QualityRuleCode


class _MemoryQuarantineRepository:
    def __init__(self, records):
        self.records = {str(record.id): record for record in records}

    async def claim(self, record_id, operator_id, lease_seconds=900):
        del lease_seconds
        current = self.records.get(record_id)
        if current is None or current.status is not QuarantineStatus.PENDING:
            return None
        event = QuarantineResolutionEvent(
            fromStatus=QuarantineStatus.PENDING,
            toStatus=QuarantineStatus.REPROCESSING,
            action=QuarantineAction.REPROCESS,
            actor=operator_id,
            reason="claimed",
            attempt=current.attempt_count + 1,
        )
        updated = current.model_copy(
            update={
                "status": QuarantineStatus.REPROCESSING,
                "claimed_by": operator_id,
                "attempt_count": current.attempt_count + 1,
                "resolution_history": [*current.resolution_history, event],
            }
        )
        self.records[record_id] = updated
        return updated

    async def release_for_retry(self, record_id, operator_id, reason, metadata=None):
        current = self.records[record_id]
        if current.status is not QuarantineStatus.REPROCESSING:
            return False
        event = QuarantineResolutionEvent(
            fromStatus=QuarantineStatus.REPROCESSING,
            toStatus=QuarantineStatus.PENDING,
            action=QuarantineAction.REPROCESS,
            actor=operator_id,
            reason=reason,
            attempt=current.attempt_count,
            metadata=metadata or {},
        )
        self.records[record_id] = current.model_copy(
            update={
                "status": QuarantineStatus.PENDING,
                "claimed_by": None,
                "resolution_history": [*current.resolution_history, event],
                "last_attempt_error": reason,
            }
        )
        return True

    async def resolve(
        self,
        record_id,
        target,
        operator_id,
        action,
        reason,
        metadata=None,
    ):
        current = self.records[record_id]
        if (
            current.status is not QuarantineStatus.REPROCESSING
            or current.claimed_by != operator_id
        ):
            return False
        event = QuarantineResolutionEvent(
            fromStatus=QuarantineStatus.REPROCESSING,
            toStatus=target,
            action=action,
            actor=operator_id,
            reason=reason,
            attempt=current.attempt_count,
            metadata=metadata or {},
        )
        self.records[record_id] = current.model_copy(
            update={
                "status": target,
                "claimed_by": None,
                "resolution_history": [*current.resolution_history, event],
                "retention_until": datetime.now(UTC) + timedelta(days=30),
                "resolution_metadata": metadata or {},
            }
        )
        return True

    async def find_blockers(self, source_unit_key):
        return [
            record
            for record in self.records.values()
            if record.source_unit_key == source_unit_key
            and record.status in {
                QuarantineStatus.PENDING,
                QuarantineStatus.REPROCESSING,
            }
        ]

    async def has_unresolved_blockers(self, source_unit_key):
        for record in await self.find_blockers(source_unit_key):
            if any(
                error.get("errorCode") == "CONFLICTING_DUPLICATE"
                for error in record.errors
            ):
                return True
        return False

    async def find_many(self, _query):
        return list(self.records.values()), None


class _MemorySourceRepository:
    def __init__(self, rows):
        self.rows = rows

    async def read_row(self, source_file_id, row_number):
        return self.rows.get((source_file_id, row_number))


class _MemoryTransactionWriter:
    def __init__(self):
        self.rows = {"TX-CONFLICT": {"amount": "100"}}

    async def insert_many(self, documents, ordered=True):
        del ordered
        document = documents[0]
        key = document["ingestion_key"]
        if key not in self.rows:
            self.rows[key] = document
            return BatchWriteResult(inserted=1)
        existing = self.rows[key]
        same = existing.get("amount") == document.get("amount")
        detail = DuplicateDetail(
            identify="MOMO",
            ingestion_key=key,
            duplicate_type=(
                QualityRuleCode.EQUIVALENT_DUPLICATE
                if same
                else QualityRuleCode.CONFLICTING_DUPLICATE
            ),
            incoming_index=0,
            incoming_fingerprint="incoming-fingerprint",
            existing_fingerprint="existing-fingerprint",
        )
        return BatchWriteResult(
            inserted=0,
            duplicates=1,
            equivalent_duplicates=int(same),
            conflicting_duplicates=int(not same),
            duplicate_details=[detail],
        )


class _MemoryCheckpointRepository:
    def __init__(self):
        self.checkpoint = IngestionCheckpoint(
            partner="MOMO",
            fetchConfigId="fetch-1",
            sourceType="API",
            streamKey="MOMO:daily",
            mode=IngestionMode.SCHEDULED,
        )

    async def claim_unit(self, **_kwargs):
        if self.checkpoint.last_completed_unit_key == "unit-conflict":
            return self.checkpoint, False
        self.checkpoint = self.checkpoint.model_copy(
            update={
                "status": CheckpointStatus.PROCESSING,
                "current_unit_key": "unit-conflict",
                "claim_id": "claim-1",
            }
        )
        return self.checkpoint, True

    async def mark_completed(self, *_args, **_kwargs):
        return True

    async def advance(self, _checkpoint, *, unit_key):
        self.checkpoint = self.checkpoint.model_copy(
            update={
                "status": CheckpointStatus.DISCOVERED,
                "current_unit_key": None,
                "last_completed_unit_key": unit_key,
            }
        )
        return True

    async def mark_failed(self, *_args, **_kwargs):
        return True


def _record(**overrides):
    payload = {
        "sourceFileId": "file-1",
        "sourceUnitKey": "unit-1",
        "partner": "MOMO",
        "reconciliationDate": datetime(2026, 8, 1, tzinfo=UTC),
        "rowNumber": 7,
        "rawRow": ("TX-001", "100"),
        "errors": [{"errorCode": "INVALID_TIMESTAMP"}],
        "phase": QuarantinePhase.VALIDATION,
    }
    payload.update(overrides)
    return IngestionQuarantineRecord(**payload)


def _request(record, mode, **overrides):
    payload = {
        "recordId": str(record.id),
        "operatorId": "operator-1",
        "mode": mode,
    }
    payload.update(overrides)
    return QuarantineReprocessRequest(**payload)


@pytest.mark.asyncio
async def test_quarantine_lifecycle_preserves_state_evidence_and_resumes_once():
    invalid = _record(sourceFileId="file-invalid", sourceUnitKey="unit-invalid")
    rejected = _record(sourceFileId="file-rejected", sourceUnitKey="unit-rejected")
    equivalent = _record(
        sourceFileId="file-equivalent",
        sourceUnitKey="unit-equivalent",
        rowNumber=4,
        rawRow=("TX-CONFLICT", "100"),
        errors=[{"errorCode": "EQUIVALENT_DUPLICATE"}],
        phase=QuarantinePhase.BATCH,
    )
    conflict = _record(
        sourceFileId="file-conflict",
        sourceUnitKey="unit-conflict",
        rowNumber=3,
        rawRow=("TX-CONFLICT", "999"),
        errors=[{"errorCode": "CONFLICTING_DUPLICATE"}],
        phase=QuarantinePhase.BATCH,
        existingFingerprint="existing-fingerprint",
    )
    quarantine = _MemoryQuarantineRepository([invalid, rejected, equivalent, conflict])
    source = _MemorySourceRepository(
        {
            ("file-invalid", 7): ("TX-INVALID", "bad-date"),
            ("file-equivalent", 4): ("TX-CONFLICT", "100"),
            ("file-conflict", 3): ("TX-CONFLICT", "999"),
        }
    )
    writer = _MemoryTransactionWriter()

    class Processor:
        def process(self, row, _row_number):
            if row == ("TX-INVALID", "bad-date"):
                return SimpleNamespace(
                    is_valid=False,
                    data_container=None,
                    errors=[{"errorCode": "INVALID_TIMESTAMP", "reason": "bad date"}],
                )
            values = row if isinstance(row, tuple) else (row["id"], row["amount"])
            return SimpleNamespace(
                is_valid=True,
                data_container={"ingestion_key": values[0], "amount": values[1]},
                errors=[],
            )

    service = QuarantineResolutionService(
        quarantine,
        source,
        SimpleNamespace(),
        row_processor=Processor(),
        transaction_repo=writer,
        existing_fingerprint_reader=AsyncMock(
            return_value="existing-fingerprint"
        ),
    )

    invalid_attempt = await service.resolve(
        _request(invalid, QuarantineReprocessMode.REPLAY_SOURCE_ROW)
    )
    assert invalid_attempt.outcome == "VALIDATION_FAILED"
    assert quarantine.records[str(invalid.id)].status is QuarantineStatus.PENDING

    corrected = await service.resolve(
        _request(
            invalid,
            QuarantineReprocessMode.CORRECTED_ROW,
            correctedRow={"id": "TX-INVALID", "amount": "100"},
        )
    )
    assert corrected.status is QuarantineStatus.RESOLVED

    equivalent_result = await service.resolve(
        _request(equivalent, QuarantineReprocessMode.REPLAY_SOURCE_ROW)
    )
    assert equivalent_result.outcome == "EQUIVALENT_DUPLICATE"
    assert equivalent_result.status is QuarantineStatus.RESOLVED

    discarded = await service.resolve(
        _request(
            rejected,
            QuarantineReprocessMode.REJECT,
            reason="Confirmed invalid by operator.",
        )
    )
    assert discarded.status is QuarantineStatus.REJECTED

    conflict_attempt = await service.resolve(
        _request(conflict, QuarantineReprocessMode.REPLAY_SOURCE_ROW)
    )
    assert conflict_attempt.outcome == "CONFLICT_REMAINS"
    assert await quarantine.has_unresolved_blockers("unit-conflict") is True

    accepted = await service.resolve(
        _request(conflict, QuarantineReprocessMode.ACCEPT_EXISTING)
    )
    assert accepted.outcome == "ACCEPTED_EXISTING"
    assert await quarantine.has_unresolved_blockers("unit-conflict") is False

    checkpoint = _MemoryCheckpointRepository()
    unit = SourceUnitMetadata(sourceUnitKey="unit-conflict", page=1)
    reconciliation_runs: list[str] = []
    cleanup_runs: list[str] = []

    async def ingest_unit(_unit):
        reconciliation_runs.append("reconcile")
        return {"success": True, "outcome": "INGESTED"}

    async def cleanup(_unit):
        cleanup_runs.append("cleanup")

    identity = {
        "partner": "MOMO",
        "fetchConfigId": "fetch-1",
        "sourceType": "API",
        "streamKey": "MOMO:daily",
        "lastCompletedUnitKey": None,
    }
    first_resume = await resume_held_source_unit(
        checkpoint,
        quarantine,
        source_unit_key="unit-conflict",
        stream_identity=identity,
        unit=unit,
        ingest_unit=ingest_unit,
        on_unit_completed=cleanup,
    )
    second_resume = await resume_held_source_unit(
        checkpoint,
        quarantine,
        source_unit_key="unit-conflict",
        stream_identity={**identity, "lastCompletedUnitKey": "unit-conflict"},
        unit=unit,
        ingest_unit=ingest_unit,
        on_unit_completed=cleanup,
    )

    assert first_resume["success"] is True
    assert second_resume["replayed"] == 1
    assert reconciliation_runs == ["reconcile"]
    assert cleanup_runs == ["cleanup"]
    assert quarantine.records[str(invalid.id)].resolution_history
    assert quarantine.records[str(invalid.id)].retention_until is not None
    assert quarantine.records[str(equivalent.id)].retention_until is not None
    assert quarantine.records[str(rejected.id)].status is QuarantineStatus.REJECTED
    assert quarantine.records[str(rejected.id)].retention_until is not None
