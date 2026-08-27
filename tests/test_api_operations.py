from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.ingestion.quarantine import IngestionQuarantineRecord


@pytest.mark.asyncio
async def test_ingestion_operations_returns_stage_and_quarantine_summary():
    from src.api.operations import get_ingestion_operations

    created_at = datetime(2026, 8, 5, tzinfo=timezone.utc)
    file_record = MagicMock()
    file_record.created_at = created_at
    file_record.model_dump.return_value = {
        "_id": "file-1",
        "fileType": "SETTLEMENT",
        "processingStatus": "FAILED",
        "stageSummary": {"currentStage": "FINALIZING"},
    }
    quarantine_record = IngestionQuarantineRecord(
        sourceFileId="file-1",
        partner="MOMO",
        reconciliationDate=created_at,
    )
    file_repository = MagicMock()
    file_repository.find_many = AsyncMock(return_value=[file_record])
    quarantine_repository = MagicMock()
    quarantine_repository.find_pending = AsyncMock(return_value=[quarantine_record])
    quarantine_repository.summarize = AsyncMock(
        return_value={
            "pending": 4,
            "reprocessing": 2,
            "resolved": 1,
            "rejected": 3,
            "overdue": 2,
            "highPriority": 1,
        }
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=MagicMock())))

    with (
        patch("src.api.operations.ReconciliationFileRepository", return_value=file_repository),
        patch("src.api.operations.IngestionQuarantineRepository", return_value=quarantine_repository),
    ):
        result = await get_ingestion_operations(request, partner="MOMO")

    assert result["summary"] == {
        "returnedFiles": 1,
        "completedFiles": 0,
        "failedFiles": 1,
        "pendingQuarantine": 1,
    }
    assert result["files"][0]["stageSummary"]["currentStage"] == "FINALIZING"
    assert result["quarantineCounters"]["reprocessingRows"] == 2
    assert result["quarantineCounters"]["overdueRows"] == 2
    assert result["pendingQuarantine"][0]["status"] == "PENDING"


@pytest.mark.asyncio
async def test_ingestion_operations_redacts_pending_quarantine_evidence():
    from src.api.operations import get_ingestion_operations

    quarantine_record = IngestionQuarantineRecord(
        sourceFileId="file-1",
        partner="MOMO",
        reconciliationDate=datetime(2026, 8, 5, tzinfo=timezone.utc),
        rawRow={"credential": "SECRET", "amount": "10"},
        incomingFingerprint="incoming-secret",
        existingFingerprint="existing-secret",
        errors=[
            {
                "errorCode": "VALIDATION_FAILED",
                "exception": "full private traceback",
            }
        ],
    )
    file_repository = MagicMock()
    file_repository.find_many = AsyncMock(return_value=[])
    quarantine_repository = MagicMock()
    quarantine_repository.find_pending = AsyncMock(return_value=[quarantine_record])
    quarantine_repository.summarize = AsyncMock(return_value={})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=MagicMock())))

    with (
        patch("src.api.operations.ReconciliationFileRepository", return_value=file_repository),
        patch("src.api.operations.IngestionQuarantineRepository", return_value=quarantine_repository),
    ):
        result = await get_ingestion_operations(request, partner="MOMO")

    pending = result["pendingQuarantine"][0]
    assert pending["errorCodes"] == ["VALIDATION_FAILED"]
    assert "rawRow" not in pending
    assert "incomingFingerprint" not in pending
    assert "existingFingerprint" not in pending
    assert "errors" not in pending
    assert "SECRET" not in str(pending)
    assert "full private traceback" not in str(pending)
