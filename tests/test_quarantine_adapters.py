"""TDD contracts for production quarantine source and fingerprint adapters."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.core.enums import FileType, TransactionStatus
from src.domain.ingestion.models import ReconciliationFile
from src.domain.ingestion.quarantine import (
    IngestionQuarantineRecord,
    QuarantinePhase,
)
from src.domain.ingestion.raw_pages import RawIngestionPage
from src.domain.ingestion.quality import QualityRuleCode
from src.domain.partner_transaction.duplicates import (
    BatchWriteResult,
    DuplicateDetail,
    fingerprint_payload,
)
from src.domain.partner_transaction.models import DataContainer, PartnerData
from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository
from src.infrastructure.ingestion.raw_page_repository import RawIngestionPageRepository
from src.infrastructure.partner_transaction.mappers import data_container_to_row
from src.infrastructure.partner_transaction.repository import DataContainerRepository
from src.pipeline.row_batch_coordinator import RowBatchContext, RowBatchCoordinator


def _record(**overrides) -> IngestionQuarantineRecord:
    payload = {
        "sourceFileId": "file-1",
        "sourceUnitKey": "unit-1",
        "partner": "MOMO",
        "reconciliationDate": datetime(2026, 8, 26, tzinfo=UTC),
        "rowNumber": 2,
        "rawRow": ["TX-1", "10.00", "USD", "2025-01-01"],
        "phase": QuarantinePhase.BATCH,
        "ingestionKey": "TX-1",
        "existingFingerprint": "existing-fingerprint",
    }
    payload.update(overrides)
    return IngestionQuarantineRecord(**payload)


@pytest.mark.asyncio
async def test_file_repository_reads_authoritative_row_from_claimed_source(tmp_path):
    source_path = tmp_path / "settlement.csv"
    source_path.write_text("id,amount,currency,date\nTX-1,10.00,USD,2025-01-01\n")
    source_file = ReconciliationFile(
        partner="MOMO",
        file_name=source_path.name,
        file_hash="hash-1",
        file_type=FileType.SETTLEMENT,
        reconciliation_date=datetime(2026, 8, 26, tzinfo=UTC),
        sourceFilePath=str(source_path),
    )
    repository = ReconciliationFileRepository.__new__(ReconciliationFileRepository)
    repository.find_one = AsyncMock(return_value=source_file)

    row = await repository.read_row(str(source_file.id), 2)

    assert row == ("TX-1", "10.00", "USD", "2025-01-01")
    repository.find_one.assert_awaited_once_with({"_id": str(source_file.id)})


@pytest.mark.asyncio
async def test_raw_page_repository_reads_row_from_gridfs_backed_page(tmp_path):
    payload_path = tmp_path / "page-1.json"
    payload_path.write_text(json.dumps({"items": [{"id": "TX-1"}, {"id": "TX-2"}]}))
    page = RawIngestionPage(
        stageKey="stage-1",
        partner="MOMO",
        fetchConfigId="fetch-1",
        sourceType="API",
        streamKey="MOMO:daily",
        reconciliationDate=datetime(2026, 8, 26, tzinfo=UTC),
        sourceUnitKey="unit-1",
        localPath=str(payload_path),
    )
    repository = RawIngestionPageRepository.__new__(RawIngestionPageRepository)
    repository.find_one = AsyncMock(return_value=page)

    row = await repository.read_row("unit-1", 2)

    assert row == {"id": "TX-2"}
    repository.find_one.assert_awaited_once_with({"sourceUnitKey": "unit-1"})


@pytest.mark.asyncio
async def test_conflict_quarantine_preserves_ingestion_key_and_row_context():
    quarantine_repo = SimpleNamespace(create_many=AsyncMock(return_value=1))
    coordinator = RowBatchCoordinator(
        reader=MagicMock(),
        start_row=2,
        row_processor=MagicMock(),
        batch_writer=MagicMock(),
        state=MagicMock(),
        batch_size=10,
        logger=MagicMock(),
        context=RowBatchContext(
            file_id="file-1",
            partner="MOMO",
            reconciliation_date=datetime(2026, 8, 26, tzinfo=UTC),
            fetch_unit_key="unit-1",
            config_version="mapping-v1",
        ),
        quarantine_repo=quarantine_repo,
        emit_stage=MagicMock(),
    )
    result = BatchWriteResult(
        inserted=0,
        duplicates=1,
        conflicting_duplicates=1,
        duplicate_details=[
            DuplicateDetail(
                identify="MOMO",
                ingestion_key="TX-1",
                duplicate_type=QualityRuleCode.CONFLICTING_DUPLICATE,
                incoming_index=0,
                incoming_fingerprint="incoming",
                existing_fingerprint="existing",
                row_context={
                    "rowNumber": 2,
                    "rawRow": ("TX-1", "10.00", "USD", "2025-01-01"),
                },
            )
        ],
    )

    await coordinator._quarantine_conflicts(result)

    record = quarantine_repo.create_many.await_args.args[0][0]
    assert record.ingestion_key == "TX-1"
    assert record.row_number == 2
    assert record.raw_row == ["TX-1", "10.00", "USD", "2025-01-01"]


@pytest.mark.asyncio
async def test_transaction_repository_reads_existing_fingerprint_for_quarantine_record():
    existing = DataContainer(
        identify="MOMO",
        workflowType="UPC",
        reconciliationDate=datetime(2026, 8, 26, tzinfo=UTC),
        sourceFileId=str(uuid4()),
        ingestionKey="TX-1",
        partnerData=PartnerData(
            _id="TX-1",
            trace=None,
            status=TransactionStatus.SUCCESS.value,
            amount="10.00",
            currency="USD",
            transDate=datetime(2025, 1, 1, tzinfo=UTC),
            extra={},
        ),
    )
    repository = DataContainerRepository.__new__(DataContainerRepository)
    repository.find_by_ingestion_key = AsyncMock(return_value=existing)

    fingerprint = await repository.find_existing_fingerprint(_record())

    assert fingerprint == fingerprint_payload(data_container_to_row(existing))
    repository.find_by_ingestion_key.assert_awaited_once_with("MOMO", "TX-1")
