from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.loader import ConfigLoader
from src.core.enums import FileType, ProcessingStatus
from src.core.types import FieldMapping, FieldMappingType
from src.domain.ingestion.models import ReconciliationFile
from src.domain.ingestion.quality import QualityEvaluation, QualityRuleCode
from src.domain.partner_transaction.duplicates import (
    BatchWriteResult,
    DuplicateDetail,
)
from src.domain.mapping.models import MappingConfig
from src.normalizer.normalizer import NormalizationResult
from src.pipeline.batch_writer import BatchWriteCoordinator
from src.pipeline.config_preparation import ConfigPreparationService
from src.pipeline.file_claim import FileClaimService
from src.pipeline.finalizer import IngestionRunFinalizer
from src.domain.ingestion.quarantine import (
    IngestionQuarantineRecord,
    sanitize_raw_row,
)
from src.pipeline.row_processor import RowProcessor
from src.pipeline.row_batch_coordinator import flush_quarantine_records
from src.pipeline.row_pipeline import RowPipelineExecutor, RowPipelineRequest
from src.pipeline.run_state import IngestionRunState


def _equivalent_duplicate_detail(
    ingestion_key: str = "duplicate-key",
) -> DuplicateDetail:
    return DuplicateDetail(
        identify="MOMO",
        ingestion_key=ingestion_key,
        duplicate_type=QualityRuleCode.EQUIVALENT_DUPLICATE,
        incoming_index=0,
        incoming_fingerprint="same",
        existing_fingerprint="same",
    )


def test_run_state_tracks_rows_keys_errors_and_batch_outcomes():
    state = IngestionRunState()

    assert state.record_row() == 1
    state.record_valid_row("txn-1")
    state.record_row()
    state.record_invalid_row([{"field": "amount", "reason": "invalid"}])
    state.record_batch_result(
        BatchWriteResult(
            inserted=2,
            duplicates=1,
            equivalent_duplicates=1,
            failed=1,
            duplicate_details=[_equivalent_duplicate_detail()],
        )
    )

    assert state.stats.total_rows == 2
    assert state.stats.success_rows == 2
    assert state.stats.failed_rows == 2
    assert state.stats.duplicate_rows == 1
    assert state.quality_counters == {
        "inputRows": 2,
        "persistedRows": 2,
        "rejectedRows": 1,
        "duplicateRows": 1,
        "failedRows": 1,
        "persistenceFailedRows": 1,
        "quarantinedRows": 0,
        "equivalentDuplicateRows": 1,
    }
    assert state.ingestion_keys == ["txn-1"]
    assert [error["field"] for error in state.errors] == [
        "amount",
        "transaction_duplicate",
        "batch_conflict",
    ]


def test_run_state_records_one_explicit_persistence_failure_consistently():
    state = IngestionRunState(total_rows=1)

    state.record_persistence_failure()

    assert state.failed_rows == 1
    assert state.persistence_failed_rows == 1
    assert state.stats.failed_rows == 1


def test_quarantine_sanitizes_sensitive_raw_values():
    result = sanitize_raw_row(
        {
            "token": "secret",
            "apiKey": "secret-key",
            "api-key": "secret-key-2",
            "message": "ok",
        }
    )

    assert result == {
        "token": "[REDACTED]",
        "apiKey": "[REDACTED]",
        "api-key": "[REDACTED]",
        "message": "ok",
    }


def test_row_pipeline_keeps_validation_side_effect_free():
    executor = RowPipelineExecutor(
        data_repository=MagicMock(),
        quarantine_repository=None,
        logger=MagicMock(),
        fast_mode=False,
        batch_size=100,
        write_workers=1,
        ordered_insert=False,
    )
    request = RowPipelineRequest(
        file_path="transactions.xlsx",
        config=MagicMock(
            field_mappings=[FieldMapping(path="id", column="A", type=FieldMappingType.STRING)]
        ),
        partner="MOMO",
        workflow_type="UPC",
        reconciliation_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
        source_file_id="file-1",
        file_id="file-1",
        fetch_unit_key=None,
        config_version=None,
        state=IngestionRunState(),
        emit_stage=MagicMock(),
    )

    processor = executor._build_row_processor(request)

    assert not hasattr(processor._validator, "_data_container_repo")
    assert not hasattr(processor._validator, "_reconciliation_file_repo")
    assert not hasattr(processor._validator, "validate_with_duplicates")


@pytest.mark.asyncio
async def test_pipeline_flushes_quarantine_records_as_a_batch():
    quarantine_repository = MagicMock()
    quarantine_repository.create_many = AsyncMock(return_value=2)
    state = IngestionRunState()
    records = [
        IngestionQuarantineRecord(
            source_file_id="file-1",
            partner="MOMO",
            reconciliation_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
            raw_row=["bad"],
        ),
        IngestionQuarantineRecord(
            source_file_id="file-1",
            partner="MOMO",
            reconciliation_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
            raw_row=["bad-2"],
        ),
    ]

    await flush_quarantine_records(
        records,
        repository=quarantine_repository,
        state=state,
        emit_stage=MagicMock(),
    )

    quarantine_repository.create_many.assert_awaited_once_with(records)
    assert state.quality_counters["quarantinedRows"] == 2


def test_file_claim_service_derives_stable_fetch_unit_key():
    service = FileClaimService(None, MagicMock())
    kwargs = {
        "partner": "MOMO",
        "workflow_type": "UPC",
        "file_type": FileType.SETTLEMENT,
        "reconciliation_date": datetime(2024, 1, 15, tzinfo=timezone.utc),
        "config_version": "v1",
        "metadata": {"sourceEndpoint": "/transactions", "page": 2},
    }

    assert service.derive_fetch_unit_key(**kwargs) == service.derive_fetch_unit_key(**kwargs)


def test_file_claim_service_preserves_explicit_api_source_unit_key():
    service = FileClaimService(None, MagicMock())

    key = service.derive_fetch_unit_key(
        partner="VIETTELPAY",
        workflow_type="UPC",
        file_type=FileType.SETTLEMENT,
        reconciliation_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
        config_version="v1",
        metadata={
            "sourceEndpoint": "/transactions",
            "page": 1,
            "sourceUnitKey": "api-page-1",
        },
    )

    assert key == "api-page-1"


@pytest.mark.asyncio
async def test_file_claim_reopens_failed_file_for_idempotent_retry(monkeypatch):
    failed = ReconciliationFile(
        partner="MOMO",
        file_name="file.xlsx",
        file_hash="hash-1",
        file_type=FileType.SETTLEMENT,
        reconciliation_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
        processing_status=ProcessingStatus.FAILED,
    )
    reopened = failed.model_copy(update={"processing_status": ProcessingStatus.PROCESSING})
    repository = MagicMock()
    repository.find_by_file_hash = AsyncMock(return_value=failed)
    repository.reclaim_failed_by_file_hash = AsyncMock(return_value=reopened)
    classify_scope = AsyncMock(
        return_value={
            "scopeType": "UNCONFIRMED",
            "scopeConfidence": 0.0,
            "scopeReason": [],
            "scopeSignals": {},
        }
    )
    monkeypatch.setattr("src.pipeline.file_claim.classify_scope", classify_scope)
    service = FileClaimService(MagicMock(), repository)

    result = await service.claim(
        file_path="/tmp/file.xlsx",
        partner="MOMO",
        workflow_type="UPC",
        file_type=FileType.SETTLEMENT,
        reconciliation_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
        config_version=None,
        fetch_unit_metadata=None,
        file_hash="hash-1",
    )

    assert result.created is True
    assert result.file_record.processing_status == ProcessingStatus.PROCESSING
    repository.reclaim_failed_by_file_hash.assert_awaited_once_with("MOMO", "hash-1")
    classify_scope.assert_not_awaited()


@pytest.mark.asyncio
async def test_file_claim_skips_scope_for_existing_processing_file(monkeypatch):
    existing = ReconciliationFile(
        partner="MOMO",
        file_name="file.xlsx",
        file_hash="hash-1",
        file_type=FileType.SETTLEMENT,
        reconciliation_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
        processing_status=ProcessingStatus.PROCESSING,
    )
    repository = MagicMock()
    repository.find_by_file_hash = AsyncMock(return_value=existing)
    classify_scope = AsyncMock()
    monkeypatch.setattr("src.pipeline.file_claim.classify_scope", classify_scope)

    result = await FileClaimService(MagicMock(), repository).claim(
        file_path="/tmp/file.xlsx",
        partner="MOMO",
        workflow_type="UPC",
        file_type=FileType.SETTLEMENT,
        reconciliation_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
        config_version=None,
        fetch_unit_metadata=None,
        file_hash="hash-1",
    )

    assert result.created is False
    assert result.duplicate_code == "file_duplicate"
    classify_scope.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_retry_after_persistence_failure_reuses_file_claim(
    monkeypatch,
    tmp_path,
):
    import openpyxl

    file_path = tmp_path / "retry.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.append(["ID", "Amount", "Status"])
    sheet.append(["txn-1", 10, "Success"])
    workbook.save(file_path)

    config = MappingConfig(
        partner="MOMO",
        workflow_type="UPC",
        file_type=FileType.SETTLEMENT,
        sheet_name="Sheet1",
        field_mappings=[
            FieldMapping(path="id", column="A", type=FieldMappingType.STRING, required=True),
            FieldMapping(path="amount", column="B", type=FieldMappingType.DECIMAL, required=True),
            FieldMapping(path="currency", constant="VND", type=FieldMappingType.CONSTANT),
            FieldMapping(
                path="status",
                column="C",
                type=FieldMappingType.MAPPING,
                mapping={"Success": "SUCCESS"},
            ),
        ],
    )
    file_repository = MagicMock()
    file_repository.find_by_file_hash = AsyncMock(side_effect=[None, None])
    file_repository.create_or_get_by_file_hash = AsyncMock(
        side_effect=lambda document: (document, True)
    )
    file_repository.update_processing_stats = AsyncMock(return_value=True)
    file_repository.update_status = AsyncMock(return_value=True)
    file_repository.update_stage_summary = AsyncMock(return_value=True)

    data_repository = MagicMock()
    data_repository.insert_many = AsyncMock(
        side_effect=[
            RuntimeError("temporary database outage"),
            BatchWriteResult(
                inserted=0,
                duplicates=1,
                equivalent_duplicates=1,
                duplicate_details=[_equivalent_duplicate_detail()],
            ),
        ]
    )
    config_loader = MagicMock(spec=ConfigLoader)
    config_loader.load_by_partner_type = AsyncMock(return_value=config)
    logger = MagicMock()

    monkeypatch.setattr(
        "src.pipeline.file_claim.classify_scope",
        AsyncMock(
            return_value={
                "scopeType": "UNCONFIRMED",
                "scopeConfidence": 0.0,
                "scopeReason": [],
                "scopeSignals": {},
            }
        ),
    )
    from src.pipeline import IngestionPipeline

    pipeline = IngestionPipeline(
        db=MagicMock(),
        config_loader=config_loader,
        file_repo=file_repository,
        partner_repo=data_repository,
        mapping_repo=MagicMock(),
        logger=logger,
        write_workers=1,
    )
    pipeline._compute_file_hash = AsyncMock(return_value="retry-hash")

    first = await pipeline.process_file(
        file_path=str(file_path),
        partner="MOMO",
        workflow_type="UPC",
        file_type=FileType.SETTLEMENT,
        reconciliation_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
    )
    failed_record = first.file_record
    file_repository.find_by_file_hash.side_effect = [failed_record]
    file_repository.reclaim_failed_by_file_hash = AsyncMock(
        side_effect=lambda _partner, _file_hash: failed_record.model_copy(
            update={"processing_status": ProcessingStatus.PROCESSING}
        )
    )

    second = await pipeline.process_file(
        file_path=str(file_path),
        partner="MOMO",
        workflow_type="UPC",
        file_type=FileType.SETTLEMENT,
        reconciliation_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
    )

    assert first.outcome == "FAILED"
    assert second.stats.duplicate_rows == 1
    assert second.quality_counters["duplicateRows"] == 1
    assert second.file_record.id == failed_record.id
    file_repository.reclaim_failed_by_file_hash.assert_awaited_once_with(
        "MOMO", "retry-hash"
    )


@pytest.mark.asyncio
async def test_config_preparation_service_loads_and_interpolates_mapping():
    config = MappingConfig(
        partner="MOMO",
        workflow_type="UPC",
        file_type=FileType.SETTLEMENT,
        sheet_name="daily-{date:%Y%m%d}",
        field_mappings=[],
    )
    loader = MagicMock(spec=ConfigLoader)
    loader.load_by_partner_type = AsyncMock(return_value=config)
    service = ConfigPreparationService(loader, MagicMock(), MagicMock())

    result = await service.prepare(
        file_path="file.xlsx",
        file_name="file.xlsx",
        partner="MOMO",
        workflow_type="UPC",
        file_type=FileType.SETTLEMENT,
        reconciliation_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
        config_version=None,
        source_file_id="00000000-0000-0000-0000-000000000001",
        enable_health_check=False,
    )

    assert result.sheet_name == "daily-20240115"
    loader.load_by_partner_type.assert_awaited_once()


def test_row_processor_builds_canonical_transaction():
    normalizer = MagicMock()
    normalizer.normalize.return_value = NormalizationResult(
        data={
            "id": "txn-1",
            "trace": "trace-1",
            "amount": Decimal("10.00"),
            "currency": "VND",
            "status": "SUCCESS",
        }
    )
    validator = MagicMock()
    validator.validate.return_value = QualityEvaluation()
    processor = RowProcessor(
        normalizer=normalizer,
        validator=validator,
        fast_mode=False,
        partner="MOMO",
        workflow_type="UPC",
        reconciliation_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
        source_file_id="00000000-0000-0000-0000-000000000001",
    )

    result = processor.process(("raw",), 2)

    assert result.is_valid
    assert result.ingestion_key == "txn-1"
    assert str(result.data_container.source_file_id) == "00000000-0000-0000-0000-000000000001"


def test_row_processor_fast_mode_builds_repository_ready_container():
    from src.domain.partner_transaction.models import FastDataContainer

    normalizer = MagicMock()
    normalizer.normalize.return_value = NormalizationResult(
        data={
            "id": "txn-1",
            "trace": "trace-1",
            "amount": Decimal("10.00"),
            "currency": "VND",
            "status": "SUCCESS",
            "transDate": None,
            "extra": {},
        }
    )
    processor = RowProcessor(
        normalizer=normalizer,
        validator=MagicMock(),
        fast_mode=True,
        partner="MOMO",
        workflow_type="UPC",
        reconciliation_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
        source_file_id="00000000-0000-0000-0000-000000000001",
    )

    result = processor.process(("raw",), 2)

    assert isinstance(result.data_container, FastDataContainer)
    assert result.data_container.partner_data.id == "txn-1"
    assert result.data_container.ingestion_key == "txn-1"


@pytest.mark.asyncio
async def test_batch_writer_respects_repository_contract():
    repository = MagicMock()
    repository.insert_many = AsyncMock(return_value=BatchWriteResult(inserted=1))
    writer = BatchWriteCoordinator(repository, workers=1, ordered=False)

    result = await writer.submit([{"id": "txn-1"}])

    assert result == [BatchWriteResult(inserted=1)]
    repository.insert_many.assert_awaited_once_with([{"id": "txn-1"}], ordered=False)


@pytest.mark.asyncio
async def test_finalizer_completes_and_fails_runs():
    repository = MagicMock()
    repository.update_processing_stats = AsyncMock(return_value=True)
    repository.update_status = AsyncMock(return_value=True)
    repository.update_stage_summary = AsyncMock(return_value=True)
    logger = MagicMock()
    finalizer = IngestionRunFinalizer(logger)
    file_record = MagicMock()
    file_record.id = "file-1"
    state = IngestionRunState(total_rows=2, success_rows=1, failed_rows=1)

    await finalizer.complete(repository, file_record, state, 12.5)
    await finalizer.fail(repository, file_record, state, RuntimeError("boom"))

    assert file_record.processing_status == ProcessingStatus.FAILED
    assert repository.update_status.await_count == 2
    logger.emit_file_completed.assert_called_once()
    logger.emit_file_failed.assert_called_once()


@pytest.mark.asyncio
async def test_finalizer_does_not_classify_generic_failure_as_persistence_failure():
    repository = MagicMock()
    repository.update_processing_stats = AsyncMock(return_value=True)
    repository.update_status = AsyncMock(return_value=True)
    repository.update_stage_summary = AsyncMock(return_value=True)
    file_record = MagicMock()
    file_record.id = "file-1"
    state = IngestionRunState()

    await IngestionRunFinalizer(MagicMock()).fail(
        repository,
        file_record,
        state,
        RuntimeError("reader failed"),
    )

    assert state.quality_counters["failedRows"] == 0
    assert state.errors[-1] == {
        "field": "ingestion_error",
        "reason": "reader failed",
    }
