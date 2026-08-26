"""Production-composition contract for quarantine reprocessing."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.ingestion.quarantine_reprocessing import (
    QuarantineReprocessMode,
    QuarantineReprocessRequest,
)
from src.core.enums import FileType, TransactionStatus
from src.core.types import FieldMapping, FieldMappingType
from src.domain.ingestion.quarantine import (
    IngestionQuarantineRecord,
    QuarantinePhase,
    QuarantineResolutionEvent,
    QuarantineStatus,
)
from src.domain.mapping.models import MappingConfig
from src.domain.partner_transaction.duplicates import BatchWriteResult
from src.infrastructure.ingestion.composition import build_quarantine_resolution_service


def _mapping_config() -> MappingConfig:
    return MappingConfig(
        partner="MOMO",
        workflowType="UPC",
        fileType=FileType.SETTLEMENT,
        sheetName="Sheet1",
        startRow=1,
        configVersion="mapping-v1",
        fieldMappings=[
            FieldMapping(path="id", column=1, type=FieldMappingType.STRING, required=True),
            FieldMapping(path="amount", column=2, type=FieldMappingType.DECIMAL, required=True),
            FieldMapping(path="currency", column=3, type=FieldMappingType.STRING, required=True),
            FieldMapping(path="transDate", column=4, type=FieldMappingType.DATE, required=True),
            FieldMapping(
                path="status",
                type=FieldMappingType.CONSTANT,
                constant=TransactionStatus.SUCCESS.value,
                required=True,
            ),
        ],
    )


def _record() -> IngestionQuarantineRecord:
    return IngestionQuarantineRecord(
        sourceFileId="file-1",
        sourceUnitKey="unit-1",
        partner="MOMO",
        reconciliationDate=datetime(2026, 8, 26, tzinfo=UTC),
        rowNumber=2,
        rawRow=["TX-1", "10.00", "USD", "2025-01-01"],
        errors=[{"errorCode": "INVALID_TIMESTAMP"}],
        phase=QuarantinePhase.VALIDATION,
        configVersion="mapping-v1",
        ingestionKey="TX-1",
    )


@pytest.mark.asyncio
async def test_production_composition_reprocesses_with_approved_mapping():
    record = _record()
    claimed = record.model_copy(
        update={
            "status": QuarantineStatus.REPROCESSING,
            "claimedBy": "operator-1",
            "resolutionHistory": [
                QuarantineResolutionEvent(
                    fromStatus=QuarantineStatus.PENDING,
                    toStatus=QuarantineStatus.REPROCESSING,
                    action="REPROCESS",
                    actor="operator-1",
                    reason="claimed",
                    attempt=2,
                )
            ],
        }
    )
    quarantine_repo = SimpleNamespace(
        claim=AsyncMock(return_value=claimed),
        release_for_retry=AsyncMock(return_value=True),
        resolve=AsyncMock(return_value=True),
    )
    source_file_repo = SimpleNamespace(
        read_row=AsyncMock(return_value=("TX-1", "10.00", "USD", "2025-01-01"))
    )
    transaction_repo = SimpleNamespace(
        insert_many=AsyncMock(return_value=BatchWriteResult(inserted=1))
    )
    config_loader = SimpleNamespace(
        load_by_version=AsyncMock(return_value=_mapping_config()),
        load_by_partner_type=AsyncMock(return_value=_mapping_config()),
    )

    service = build_quarantine_resolution_service(
        object(),
        quarantine_repo=quarantine_repo,
        source_file_repo=source_file_repo,
        raw_page_repo=SimpleNamespace(),
        transaction_repo=transaction_repo,
        config_loader=config_loader,
        audit_recorder=AsyncMock(),
    )

    result = await service.resolve(
        QuarantineReprocessRequest(
            recordId=str(record.id),
            operatorId="operator-1",
            mode=QuarantineReprocessMode.REPLAY_SOURCE_ROW,
        )
    )

    assert result.success is True
    assert result.status is QuarantineStatus.RESOLVED
    config_loader.load_by_version.assert_awaited_once_with("MOMO", "mapping-v1")
    transaction_repo.insert_many.assert_awaited_once()
    quarantine_repo.resolve.assert_awaited_once()


@pytest.mark.asyncio
async def test_production_composition_accepts_existing_using_repository_fingerprint():
    record = _record().model_copy(update={"existing_fingerprint": "existing-fingerprint"})
    claimed = record.model_copy(
        update={
            "status": QuarantineStatus.REPROCESSING,
            "claimedBy": "operator-1",
        }
    )
    quarantine_repo = SimpleNamespace(
        claim=AsyncMock(return_value=claimed),
        release_for_retry=AsyncMock(return_value=True),
        resolve=AsyncMock(return_value=True),
    )
    transaction_repo = SimpleNamespace(
        find_existing_fingerprint=AsyncMock(return_value="existing-fingerprint")
    )

    service = build_quarantine_resolution_service(
        object(),
        quarantine_repo=quarantine_repo,
        source_file_repo=SimpleNamespace(),
        raw_page_repo=SimpleNamespace(),
        row_processor=SimpleNamespace(),
        transaction_repo=transaction_repo,
        audit_recorder=AsyncMock(),
    )

    result = await service.resolve(
        QuarantineReprocessRequest(
            recordId=str(record.id),
            operatorId="operator-1",
            mode=QuarantineReprocessMode.ACCEPT_EXISTING,
        )
    )

    assert result.success is True
    assert result.outcome == "ACCEPTED_EXISTING"
    transaction_repo.find_existing_fingerprint.assert_awaited_once_with(claimed)
    quarantine_repo.resolve.assert_awaited_once()
