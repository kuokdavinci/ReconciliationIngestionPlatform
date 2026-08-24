"""Focused acceptance tests for the Workstream B quality contract."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.core.enums import FileType, TransactionStatus
from src.application.ingestion.contracts import serialize_quality_violation
from src.application.ingestion.quality_policy import (
    OrchestrationAction,
    orchestration_action_for,
)
from src.domain.ingestion.quality import (
    QualityDecision,
    QualityEvaluation,
    QualityOutcome,
    QualityPhase,
    QualityRuleCode,
    QualitySeverity,
    QualitySummary,
    QualityViolation,
)
from src.core.types import FieldMapping, FieldMappingType
from src.domain.mapping.models import MappingConfig
from src.domain.partner_transaction.duplicates import (
    BatchWriteResult,
    DuplicateDetail,
    fingerprint_payload,
)
from src.domain.partner_transaction.models import DataContainer, PartnerData
from src.pipeline.quality_gate import FileQualityGate
from src.pipeline.batch_writer import BatchWriteCoordinator
from src.pipeline.row_processor import RowProcessor
from src.pipeline.row_batch_coordinator import RowBatchContext, RowBatchCoordinator
from src.pipeline.row_processor import RowOutcome
from src.pipeline.run_state import IngestionRunState
from src.normalizer.normalizer import TransactionNormalizer
from src.validators.validator import Validator


def _config(*mappings: FieldMapping, signature: dict | None = None) -> MappingConfig:
    return MappingConfig(
        partner="MOMO",
        workflowType="UPC",
        fileType=FileType.SETTLEMENT,
        sheetName="Sheet1",
        startRow=2,
        fieldMappings=list(mappings),
        configVersion="v1",
        structureSignature=signature,
    )


def _base_mappings() -> list[FieldMapping]:
    return [
        FieldMapping(path="id", column=1, type=FieldMappingType.STRING, required=True),
        FieldMapping(path="amount", column=2, type=FieldMappingType.DECIMAL, required=True),
        FieldMapping(path="currency", column=3, type=FieldMappingType.STRING, required=True),
        FieldMapping(
            path="status",
            column=4,
            type=FieldMappingType.CONSTANT,
            constant=TransactionStatus.SUCCESS.value,
            required=True,
        ),
    ]


def _timestamp_processor(*, fast_mode: bool) -> RowProcessor:
    mappings = [
        FieldMapping(
            path="id",
            column=1,
            type=FieldMappingType.STRING,
            required=True,
        ),
        FieldMapping(
            path="amount",
            column=2,
            type=FieldMappingType.DECIMAL,
            required=True,
        ),
        FieldMapping(
            path="currency",
            column=3,
            type=FieldMappingType.STRING,
            required=True,
        ),
        FieldMapping(
            path="transDate",
            column=4,
            type=FieldMappingType.DATE,
            required=True,
        ),
        FieldMapping(
            path="status",
            type=FieldMappingType.CONSTANT,
            constant=TransactionStatus.SUCCESS.value,
            required=True,
        ),
    ]
    return RowProcessor(
        normalizer=TransactionNormalizer(mappings),
        validator=Validator(),
        fast_mode=fast_mode,
        partner="INTER",
        workflow_type="SETTLEMENT",
        reconciliation_date=datetime(2025, 1, 1, tzinfo=UTC),
        source_file_id=uuid4(),
    )


def _transaction(
    ingestion_key: str,
    *,
    amount: Decimal = Decimal("100.00"),
    metadata: dict | None = None,
) -> DataContainer:
    return DataContainer(
        identify="MOMO",
        workflowType="UPC",
        reconciliationDate=datetime(2026, 8, 19, tzinfo=timezone.utc),
        sourceFileId=uuid4(),
        ingestionKey=ingestion_key,
        partnerData=PartnerData(
            _id=f"id-{ingestion_key}",
            trace=f"trace-{ingestion_key}",
            status="SUCCESS",
            amount=amount,
            currency="VND",
            transDate=datetime(2026, 8, 19, tzinfo=timezone.utc),
            extra=metadata or {"channel": "app"},
        ),
    )


def test_quality_violation_uses_message_internally_and_reason_at_boundary():
    violation = QualityViolation(
        code=QualityRuleCode.INVALID_AMOUNT,
        phase=QualityPhase.VALIDATION,
        severity=QualitySeverity.ERROR,
        outcome=QualityOutcome.REJECT,
        field="amount",
        message="Amount must be a decimal.",
        expected="Decimal >= 0",
        actual="bad",
        row=7,
        trace="trace-7",
    )

    assert violation.message == "Amount must be a decimal."
    payload = serialize_quality_violation(violation)
    assert payload["reason"] == "Amount must be a decimal."
    assert payload["errorCode"] == "INVALID_AMOUNT"
    assert payload["phase"] == "VALIDATION"
    assert payload["row"] == 7


def test_serialized_violation_retains_field_key_when_context_is_global():
    violation = QualityViolation(
        code=QualityRuleCode.CONFIG_VALIDATION,
        phase=QualityPhase.CONFIGURATION,
        severity=QualitySeverity.FATAL,
        outcome=QualityOutcome.BATCH_FATAL,
        message="Global configuration is invalid.",
    )

    assert serialize_quality_violation(violation)["field"] is None


def test_fatal_violation_has_precedence_over_declared_warning_outcome():
    evaluation = QualityEvaluation(
        outcome=QualityOutcome.WARNING,
        violations=[
            QualityViolation(
                code=QualityRuleCode.CONFIG_VALIDATION,
                phase=QualityPhase.CONFIGURATION,
                severity=QualitySeverity.FATAL,
                outcome=QualityOutcome.BATCH_FATAL,
                message="Configuration is structurally invalid.",
            )
        ],
    )

    assert evaluation.outcome is QualityOutcome.BATCH_FATAL
    assert evaluation.decision is QualityDecision.FAIL


def test_quality_summary_holds_conflicting_duplicate_for_review():
    evaluation = QualityEvaluation(
        outcome=QualityOutcome.CONFLICTING_DUPLICATE,
        violations=[
            QualityViolation(
                code=QualityRuleCode.CONFLICTING_DUPLICATE,
                phase=QualityPhase.PERSISTENCE,
                severity=QualitySeverity.ERROR,
                outcome=QualityOutcome.CONFLICTING_DUPLICATE,
                field="ingestion_key",
                message="Duplicate key has a different payload.",
            )
        ],
    )

    summary = QualitySummary.from_evaluations([evaluation])

    assert summary.decision is QualityDecision.REVIEW
    assert orchestration_action_for(summary) is OrchestrationAction.HOLD_FOR_REVIEW
    assert summary.rule_counts[QualityRuleCode.CONFLICTING_DUPLICATE.value] == 1
    assert summary.top_rule_codes == [QualityRuleCode.CONFLICTING_DUPLICATE.value]


def test_file_gate_fails_without_required_schema_path():
    config = _config(
        FieldMapping(path="id", column=1, type=FieldMappingType.STRING, required=True),
        FieldMapping(path="currency", column=2, type=FieldMappingType.STRING),
    )

    evaluation = FileQualityGate().evaluate(
        config,
        headers=["id", "currency"],
        column_count=2,
    )

    assert evaluation.decision is QualityDecision.FAIL
    assert any(item.code is QualityRuleCode.REQUIRED_SCHEMA_PATH for item in evaluation.violations)
    assert all(item.outcome is QualityOutcome.BATCH_FATAL for item in evaluation.violations)


def test_file_gate_fails_for_empty_inspected_source_field_schema():
    config = _config(
        FieldMapping(
            path="id",
            sourceField="id",
            type=FieldMappingType.STRING,
            required=True,
        ),
        FieldMapping(
            path="amount",
            sourceField="amount",
            type=FieldMappingType.DECIMAL,
            required=True,
        ),
        FieldMapping(
            path="currency",
            sourceField="currency",
            type=FieldMappingType.STRING,
            required=True,
        ),
        FieldMapping(
            path="status",
            sourceField="status",
            type=FieldMappingType.STRING,
            required=True,
        ),
    )

    evaluation = FileQualityGate().evaluate(
        config,
        headers=[],
        column_count=0,
    )

    assert evaluation.decision is QualityDecision.FAIL
    assert {violation.code for violation in evaluation.violations} == {
        QualityRuleCode.MISSING_REQUIRED_SOURCE_COLUMN
    }


def test_file_gate_passes_when_required_structure_matches():
    evaluation = FileQualityGate().evaluate(
        _config(*_base_mappings()),
        headers=["id", "amount", "currency", "status"],
        column_count=4,
    )

    assert evaluation.decision is QualityDecision.PASS
    assert evaluation.violations == []


def test_file_gate_inspects_only_the_source_header(monkeypatch, tmp_path):
    from src.config.signature import StructureSignature

    sample_sizes = []

    def inspect_header(_file_path, sample_size):
        sample_sizes.append(sample_size)
        return StructureSignature(
            headers=["id", "amount", "currency", "status"],
            column_count=4,
        )

    source_path = tmp_path / "source.csv"
    source_path.touch()
    monkeypatch.setattr(
        "src.pipeline.quality_gate.compute_signature",
        inspect_header,
    )

    evaluation = FileQualityGate().evaluate(
        _config(*_base_mappings()),
        file_path=source_path,
    )

    assert evaluation.decision is QualityDecision.PASS
    assert sample_sizes == [0]


def test_file_gate_reviews_non_breaking_appended_column_drift():
    config = _config(
        *_base_mappings(),
        signature={
            "headers": ["id", "amount", "currency", "status"],
            "columnCount": 4,
        },
    )

    evaluation = FileQualityGate().evaluate(
        config,
        headers=["id", "amount", "currency", "status", "optional_note"],
        column_count=5,
    )

    assert evaluation.decision is QualityDecision.REVIEW
    assert evaluation.outcome is QualityOutcome.WARNING
    assert evaluation.violations[0].code is QualityRuleCode.SCHEMA_CONFIG_DRIFT
    assert evaluation.violations[0].severity is QualitySeverity.WARNING

    state = IngestionRunState()
    state.record_quality_evaluation(evaluation)
    assert state.warning_rows == 0
    assert state.quality_outcome_counts[QualityOutcome.WARNING.value] == 1


def test_file_gate_fails_on_breaking_structure_drift():
    expected_signature = {
        "headers": ["id", "amount", "currency", "status"],
        "columnCount": 4,
    }
    config = _config(*_base_mappings(), signature=expected_signature)

    evaluation = FileQualityGate().evaluate(
        config,
        headers=["id", "amount", "currency", "different_status"],
        column_count=4,
    )

    assert evaluation.decision is QualityDecision.FAIL
    assert any(item.code is QualityRuleCode.SCHEMA_CONFIG_DRIFT for item in evaluation.violations)


def test_unreadable_source_structure_uses_a_file_level_rule(monkeypatch, tmp_path):
    from src.pipeline.ingestion_pipeline import IngestionPipeline

    def raise_unreadable(*_args, **_kwargs):
        raise OSError("corrupt workbook")

    source_path = tmp_path / "corrupt.xlsx"
    source_path.touch()
    monkeypatch.setattr(
        "src.pipeline.quality_gate.compute_signature",
        raise_unreadable,
    )
    state = IngestionRunState()

    evaluation = IngestionPipeline._evaluate_file_quality_gate(
        object.__new__(IngestionPipeline),
        file_path=str(source_path),
        config=_config(*_base_mappings()),
        state=state,
    )

    assert evaluation.outcome is QualityOutcome.BATCH_FATAL
    assert evaluation.violations[0].code is QualityRuleCode.SOURCE_STRUCTURE_UNREADABLE
    assert QualityRuleCode.MALFORMED_ROW.value not in state.quality_rule_counts


def test_quality_gate_does_not_reclassify_programming_errors(monkeypatch):
    from src.pipeline.ingestion_pipeline import IngestionPipeline

    def raise_programming_error(*_args, **_kwargs):
        raise RuntimeError("unexpected implementation defect")

    monkeypatch.setattr(FileQualityGate, "evaluate", raise_programming_error)

    with pytest.raises(RuntimeError, match="implementation defect"):
        IngestionPipeline._evaluate_file_quality_gate(
            object.__new__(IngestionPipeline),
            file_path="missing.xlsx",
            config=_config(*_base_mappings()),
            state=IngestionRunState(),
        )


def test_quality_gate_does_not_reclassify_programming_value_errors(monkeypatch):
    from src.pipeline.ingestion_pipeline import IngestionPipeline

    def raise_programming_error(*_args, **_kwargs):
        raise ValueError("invalid internal gate state")

    monkeypatch.setattr(FileQualityGate, "evaluate", raise_programming_error)

    with pytest.raises(ValueError, match="internal gate state"):
        IngestionPipeline._evaluate_file_quality_gate(
            object.__new__(IngestionPipeline),
            file_path="missing.xlsx",
            config=_config(*_base_mappings()),
            state=IngestionRunState(),
        )


@pytest.mark.asyncio
async def test_config_preparation_failure_becomes_non_retryable_quality_fail():
    from src.application.ingestion.contracts import ProcessFileCommand
    from src.config.loader import ConfigLoadError
    from src.pipeline.ingestion_pipeline import IngestionPipeline
    from src.pipeline.quality_gate import QualityGateFailure

    pipeline = object.__new__(IngestionPipeline)
    pipeline._logger = MagicMock()
    pipeline._mapping_repo = MagicMock()
    pipeline._config_preparation = MagicMock()
    pipeline._config_preparation.prepare = AsyncMock(
        side_effect=ConfigLoadError(message="Mapping configuration is invalid.")
    )
    claimed = MagicMock(
        run_id="run-1",
        source_file_id="file-1",
        file_name="source.xlsx",
    )
    state = IngestionRunState()

    with pytest.raises(QualityGateFailure):
        await pipeline._prepare_mapping(
            ProcessFileCommand(
                file_path="source.xlsx",
                partner="MOMO",
                workflow_type="UPC",
                file_type=FileType.SETTLEMENT,
                reconciliation_date=datetime(2026, 8, 19, tzinfo=timezone.utc),
            ),
            claimed,
            state,
        )

    assert state.quality_decision is QualityDecision.FAIL
    assert state.orchestration_action is OrchestrationAction.FAIL
    assert state.errors[0]["errorCode"] == QualityRuleCode.CONFIG_VALIDATION.value


@pytest.mark.asyncio
async def test_row_phase_uses_the_resolved_config_version(monkeypatch):
    from src.application.ingestion.contracts import ProcessFileCommand
    from src.pipeline.ingestion_pipeline import IngestionPipeline

    executor = MagicMock()
    executor.run = AsyncMock(return_value=MagicMock())
    executor_factory = MagicMock(return_value=executor)
    monkeypatch.setattr(
        "src.pipeline.ingestion_pipeline.RowPipelineExecutor",
        executor_factory,
    )

    pipeline = object.__new__(IngestionPipeline)
    pipeline._data_repo = MagicMock()
    pipeline._quarantine_repo = MagicMock()
    pipeline._logger = MagicMock()
    pipeline._fast_mode = True
    pipeline._batch_size = 100
    pipeline._write_workers = 1
    pipeline._ordered_insert = False
    pipeline._require_repository_ports = MagicMock()
    pipeline._emit_stage = MagicMock()
    config = _config(*_base_mappings())
    command = ProcessFileCommand(
        file_path="source.csv",
        partner="MOMO",
        workflow_type="UPC",
        file_type=FileType.SETTLEMENT,
        reconciliation_date=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )
    claimed = MagicMock(
        run_id="run-1",
        source_file_id="file-1",
        fetch_unit_key="unit-1",
    )

    await pipeline._run_row_phase(
        command,
        config,
        claimed,
        IngestionRunState(),
    )

    request = executor.run.await_args.args[0]
    assert request.config_version == "v1"


def test_fast_mode_enforces_negative_amount_rule():
    processor = RowProcessor(
        normalizer=TransactionNormalizer(_base_mappings()),
        validator=Validator(),
        fast_mode=True,
        partner="MOMO",
        workflow_type="UPC",
        reconciliation_date=datetime(2026, 8, 19, tzinfo=timezone.utc),
        source_file_id="file-1",
    )

    result = processor.process(("txn-1", Decimal("-1"), "VND", None), row_number=3)

    assert result.outcome is QualityOutcome.REJECT
    assert any(item.code is QualityRuleCode.NEGATIVE_AMOUNT for item in result.violations)


def test_iso_timestamp_contract_matches_in_normal_and_fast_mode():
    row = ("txn-1", "10.00", "USD", "2025-01-01T15:00:00+07:00")

    normal = _timestamp_processor(fast_mode=False).process(row, row_number=2)
    fast = _timestamp_processor(fast_mode=True).process(row, row_number=2)

    expected = datetime(2025, 1, 1, 8, tzinfo=UTC)
    assert normal.is_valid is True
    assert fast.is_valid is True
    assert normal.outcome is fast.outcome is QualityOutcome.VALID
    assert normal.violations == fast.violations == []
    assert normal.errors == fast.errors == []
    assert normal.normalized_data == fast.normalized_data
    assert normal.data_container.partner_data.trans_date == expected
    assert fast.data_container.partner_data.trans_date == expected


def test_invalid_timestamp_contract_matches_in_normal_and_fast_mode():
    row = ("txn-1", "10.00", "USD", "not-a-timestamp")

    normal = _timestamp_processor(fast_mode=False).process(row, row_number=3)
    fast = _timestamp_processor(fast_mode=True).process(row, row_number=3)

    expected_error = {
        "field": "transDate",
        "reason": "Timestamp is not a supported date/time value.",
        "errorCode": "INVALID_TIMESTAMP",
        "phase": "NORMALIZATION",
        "severity": "ERROR",
        "outcome": "REJECT",
        "expected": (
            "ISO-8601 datetime with Z/UTC offset or an approved legacy date format"
        ),
        "actual": {"type": "str"},
        "row": 3,
    }
    assert normal.outcome is fast.outcome is QualityOutcome.REJECT
    assert normal.data_container is fast.data_container is None
    assert [item.code for item in normal.violations] == [
        QualityRuleCode.INVALID_TIMESTAMP
    ]
    assert normal.violations == fast.violations
    assert normal.errors == fast.errors == [expected_error]


@pytest.mark.parametrize(
    ("override", "expected_code"),
    [
        ({"id": ""}, QualityRuleCode.MISSING_REQUIRED_FIELD),
        ({"amount": "not-a-decimal"}, QualityRuleCode.INVALID_AMOUNT),
        ({"amount": Decimal("-1")}, QualityRuleCode.NEGATIVE_AMOUNT),
        ({"transDate": "not-a-datetime"}, QualityRuleCode.INVALID_TIMESTAMP),
        ({"status": "UNKNOWN"}, QualityRuleCode.INVALID_STATUS),
    ],
)
def test_validator_maps_promoted_rules_without_message_parsing(
    override,
    expected_code,
):
    transaction = {
        "id": "txn-1",
        "trace": "trace-1",
        "amount": Decimal("1"),
        "currency": "VND",
        "status": TransactionStatus.SUCCESS.value,
        "transDate": datetime(2026, 8, 19, tzinfo=timezone.utc),
    }
    transaction.update(override)

    evaluation = Validator().validate(transaction, row_number=3, trace="trace-1")

    assert any(item.code is expected_code for item in evaluation.violations)


def test_missing_status_emits_only_the_required_field_rule():
    evaluation = Validator().validate(
        {
            "id": "txn-1",
            "amount": Decimal("1"),
            "currency": "VND",
            "status": None,
        },
        row_number=3,
    )

    assert [item.code for item in evaluation.violations] == [QualityRuleCode.MISSING_REQUIRED_FIELD]


def test_malformed_row_violation_preserves_source_row_number():
    processor = RowProcessor(
        normalizer=TransactionNormalizer(_base_mappings()),
        validator=Validator(),
        fast_mode=True,
        partner="MOMO",
        workflow_type="UPC",
        reconciliation_date=datetime(2026, 8, 19, tzinfo=timezone.utc),
        source_file_id=uuid4(),
    )

    result = processor.process(("txn-1",), row_number=7)

    assert result.outcome is QualityOutcome.REJECT
    assert any(item.code is QualityRuleCode.MALFORMED_ROW for item in result.violations)
    assert all(item.row == 7 for item in result.violations)


@pytest.mark.parametrize("amount", [Decimal("NaN"), Decimal("Infinity")])
def test_fast_mode_rejects_non_finite_amount_as_invalid(amount):
    processor = RowProcessor(
        normalizer=TransactionNormalizer(_base_mappings()),
        validator=Validator(),
        fast_mode=True,
        partner="MOMO",
        workflow_type="UPC",
        reconciliation_date=datetime(2026, 8, 19, tzinfo=timezone.utc),
        source_file_id=uuid4(),
    )

    result = processor.process(("txn-1", amount, "VND", None), row_number=3)

    assert result.outcome is QualityOutcome.REJECT
    assert result.violations[0].code is QualityRuleCode.INVALID_AMOUNT


def test_row_processor_preserves_validator_warning_for_quality_aggregation():
    violation = QualityViolation(
        code=QualityRuleCode.MALFORMED_ROW,
        phase=QualityPhase.VALIDATION,
        severity=QualitySeverity.WARNING,
        outcome=QualityOutcome.WARNING,
        field="metadata",
        message="Metadata was normalized with a warning.",
    )
    validator = MagicMock()
    validator.validate.return_value = QualityEvaluation(
        outcome=QualityOutcome.WARNING,
        violations=[violation],
    )
    processor = RowProcessor(
        normalizer=TransactionNormalizer(_base_mappings()),
        validator=validator,
        fast_mode=True,
        partner="MOMO",
        workflow_type="UPC",
        reconciliation_date=datetime(2026, 8, 19, tzinfo=timezone.utc),
        source_file_id=uuid4(),
    )

    result = processor.process(("txn-1", Decimal("1"), "VND", None), row_number=3)

    assert result.is_valid is True
    assert result.outcome is QualityOutcome.WARNING
    assert result.violations == [violation]
    assert result.data_container is not None


def test_fingerprint_normalizes_decimal_timezone_and_sorted_metadata():
    base = {
        "partner_id": "txn-1",
        "partner_trace": "trace-1",
        "partner_status": "SUCCESS",
        "partner_amount": Decimal("10.00"),
        "partner_currency": "VND",
        "partner_trans_date": datetime(2026, 8, 19, 1, 0, tzinfo=timezone.utc),
        "partner_metadata": {"b": "2", "a": "1"},
    }
    equivalent = {
        **base,
        "partner_amount": Decimal("10.0000"),
        "partner_trans_date": datetime(2026, 8, 19, 8, 0, tzinfo=timezone(timedelta(hours=7))),
        "partner_metadata": {"a": "1", "b": "2"},
    }

    assert fingerprint_payload(base) == fingerprint_payload(equivalent)
    assert fingerprint_payload(
        {**base, "partner_metadata": {"a": "changed"}}
    ) != fingerprint_payload(base)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("amount", "metadata", "expected_type"),
    [
        (
            Decimal("100.0"),
            {"channel": "app"},
            QualityRuleCode.EQUIVALENT_DUPLICATE,
        ),
        (
            Decimal("101.00"),
            {"channel": "app"},
            QualityRuleCode.CONFLICTING_DUPLICATE,
        ),
        (
            Decimal("100.00"),
            {"channel": "branch"},
            QualityRuleCode.CONFLICTING_DUPLICATE,
        ),
    ],
    ids=["same-payload", "changed-amount", "changed-metadata"],
)
async def test_repository_classifies_conflicts_by_business_payload(
    amount,
    metadata,
    expected_type,
):
    from src.infrastructure.partner_transaction.mappers import data_container_to_row
    from src.infrastructure.partner_transaction.repository import (
        DataContainerRepository,
    )

    key = ("MOMO", "key-1")
    existing = _transaction("key-1")
    incoming = _transaction("key-1", amount=amount, metadata=metadata)
    repository = DataContainerRepository(engine=object())
    repository._insert_rows_conflict_safe = AsyncMock(return_value=(0, {key: 0}))
    repository._find_existing_for_keys = AsyncMock(
        return_value={key: data_container_to_row(existing)}
    )

    result = await repository.insert_many([incoming])

    assert result.duplicates == 1
    assert result.duplicate_details[0].duplicate_type is expected_type
    assert result.equivalent_duplicates == int(
        expected_type is QualityRuleCode.EQUIVALENT_DUPLICATE
    )
    assert result.conflicting_duplicates == int(
        expected_type is QualityRuleCode.CONFLICTING_DUPLICATE
    )
    repository._find_existing_for_keys.assert_awaited_once_with({key})


@pytest.mark.asyncio
async def test_clean_batch_skips_lookup_and_fingerprint_work(monkeypatch):
    from src.infrastructure.partner_transaction.repository import (
        DataContainerRepository,
    )

    repository = DataContainerRepository(engine=object())
    repository._insert_rows_conflict_safe = AsyncMock(return_value=(2, {}))
    repository._find_existing_for_keys = AsyncMock()

    def unexpected_fingerprint(_payload):
        raise AssertionError("clean batches must not calculate payload fingerprints")

    monkeypatch.setattr(
        "src.infrastructure.partner_transaction.repository.fingerprint_payload",
        unexpected_fingerprint,
    )

    result = await repository.insert_many([_transaction("key-1"), _transaction("key-2")])

    assert result == BatchWriteResult(inserted=2)
    repository._find_existing_for_keys.assert_not_awaited()


@pytest.mark.asyncio
async def test_conflict_batch_uses_one_bulk_existing_payload_lookup():
    from src.infrastructure.partner_transaction.mappers import data_container_to_row
    from src.infrastructure.partner_transaction.repository import (
        DataContainerRepository,
    )

    keys = {("MOMO", "key-1"), ("MOMO", "key-2")}
    repository = DataContainerRepository(engine=object())
    repository._insert_rows_conflict_safe = AsyncMock(return_value=(0, {key: 0 for key in keys}))
    repository._find_existing_for_keys = AsyncMock(
        return_value={
            ("MOMO", key): data_container_to_row(_transaction(key)) for key in ("key-1", "key-2")
        }
    )

    result = await repository.insert_many(
        [
            _transaction("key-1", amount=Decimal("101")),
            _transaction("key-2", amount=Decimal("102")),
        ]
    )

    assert result.conflicting_duplicates == 2
    repository._find_existing_for_keys.assert_awaited_once_with(keys)


def test_quality_counters_keep_duplicate_accounting_balanced():
    state = IngestionRunState(total_rows=100, rejected_rows=3, failed_rows=3)
    state.record_batch_result(
        BatchWriteResult(
            inserted=95,
            duplicates=2,
            equivalent_duplicates=1,
            conflicting_duplicates=1,
            duplicate_details=[
                DuplicateDetail(
                    identify="MOMO",
                    ingestion_key="same",
                    duplicate_type=QualityRuleCode.EQUIVALENT_DUPLICATE,
                    incoming_index=0,
                    incoming_fingerprint="same",
                    existing_fingerprint="same",
                ),
                DuplicateDetail(
                    identify="MOMO",
                    ingestion_key="conflict",
                    duplicate_type=QualityRuleCode.CONFLICTING_DUPLICATE,
                    incoming_index=1,
                    incoming_fingerprint="in",
                    existing_fingerprint="out",
                ),
            ],
        )
    )

    counters = state.quality_counters
    assert counters["inputRows"] == (
        counters["persistedRows"]
        + counters["rejectedRows"]
        + counters["duplicateRows"]
        + counters["persistenceFailedRows"]
    )
    assert counters["failedRows"] == counters["persistenceFailedRows"]
    assert counters["equivalentDuplicateRows"] == 1
    assert counters["conflictingDuplicateRows"] == 1
    assert state.quality_summary.decision is QualityDecision.REVIEW
    assert state.orchestration_action is OrchestrationAction.HOLD_FOR_REVIEW


@pytest.mark.asyncio
async def test_100_row_quality_fixture_balances_pipeline_accounting():
    class Reader:
        def iter_rows(self):
            return iter(
                [
                    (
                        f"txn-{index}",
                        Decimal("100") if index < 97 else Decimal("-1"),
                        "VND",
                        None,
                    )
                    for index in range(100)
                ]
            )

    class FixtureRepository:
        async def insert_many(self, documents, ordered=True):
            assert ordered is False
            assert len(documents) == 97
            return BatchWriteResult(
                inserted=95,
                duplicates=2,
                equivalent_duplicates=1,
                conflicting_duplicates=1,
                duplicate_details=[
                    DuplicateDetail(
                        identify="MOMO",
                        ingestion_key="txn-95",
                        duplicate_type=QualityRuleCode.EQUIVALENT_DUPLICATE,
                        incoming_index=95,
                        incoming_fingerprint="same",
                        existing_fingerprint="same",
                    ),
                    DuplicateDetail(
                        identify="MOMO",
                        ingestion_key="txn-96",
                        duplicate_type=QualityRuleCode.CONFLICTING_DUPLICATE,
                        incoming_index=96,
                        incoming_fingerprint="incoming",
                        existing_fingerprint="existing",
                    ),
                ],
            )

    class QuarantineRepository:
        def __init__(self):
            self.records = []

        async def create_many(self, records):
            self.records.extend(records)
            return len(records)

    state = IngestionRunState()
    quarantine = QuarantineRepository()
    processor = RowProcessor(
        normalizer=TransactionNormalizer(_base_mappings()),
        validator=Validator(),
        fast_mode=True,
        partner="MOMO",
        workflow_type="UPC",
        reconciliation_date=datetime(2026, 8, 19, tzinfo=timezone.utc),
        source_file_id=uuid4(),
    )

    await RowBatchCoordinator(
        reader=Reader(),
        start_row=2,
        row_processor=processor,
        batch_writer=BatchWriteCoordinator(
            FixtureRepository(),
            workers=1,
            ordered=False,
        ),
        state=state,
        batch_size=100,
        logger=MagicMock(),
        context=RowBatchContext(
            file_id="file-100",
            partner="MOMO",
            reconciliation_date=datetime(2026, 8, 19, tzinfo=timezone.utc),
            fetch_unit_key="unit-100",
            config_version="v1",
        ),
        quarantine_repo=quarantine,
        emit_stage=lambda _stage: None,
    ).run()

    counters = state.quality_counters
    assert counters["inputRows"] == 100
    assert counters["persistedRows"] == 95
    assert counters["rejectedRows"] == 3
    assert counters["duplicateRows"] == 2
    assert counters["equivalentDuplicateRows"] == 1
    assert counters["conflictingDuplicateRows"] == 1
    assert counters["persistenceFailedRows"] == 0
    assert counters["inputRows"] == (
        counters["persistedRows"]
        + counters["rejectedRows"]
        + counters["duplicateRows"]
        + counters["persistenceFailedRows"]
    )
    assert state.quality_decision is QualityDecision.REVIEW
    assert state.orchestration_action is OrchestrationAction.HOLD_FOR_REVIEW
    assert len(quarantine.records) == 4


def test_airflow_result_is_bounded_to_summary_and_counters():
    from src.application.ingestion.contracts import IngestionResult
    from src.core.types import ProcessingStats

    result = IngestionResult(
        file_record=None,
        stats=ProcessingStats(total_rows=100, success_rows=95, failed_rows=3),
        quality_counters={"inputRows": 100, "persistedRows": 95},
        quality_decision=QualityDecision.REVIEW,
        orchestration_action=OrchestrationAction.HOLD_FOR_REVIEW,
        quality_summary=QualitySummary(
            decision=QualityDecision.REVIEW,
            top_rule_codes=["CONFLICTING_DUPLICATE"],
        ),
    )

    payload = result.bounded_source_unit_result()

    assert payload == {
        "success": True,
        "outcome": "INGESTED",
        "qualityDecision": "REVIEW",
        "orchestrationAction": "HOLD_FOR_REVIEW",
        "qualityCounters": {"inputRows": 100, "persistedRows": 95},
        "topRuleCodes": ["CONFLICTING_DUPLICATE"],
    }
    assert "errors" not in payload


def test_airflow_payload_does_not_scale_with_error_detail_count():
    from src.application.ingestion.contracts import IngestionResult
    from src.core.types import ProcessingStats

    common = {
        "file_record": None,
        "stats": ProcessingStats(total_rows=10_000, success_rows=0, failed_rows=10_000),
        "quality_counters": {"inputRows": 10_000, "rejectedRows": 10_000},
        "quality_decision": QualityDecision.REVIEW,
        "quality_summary": QualitySummary(
            decision=QualityDecision.REVIEW,
            top_rule_codes=[QualityRuleCode.INVALID_AMOUNT.value],
        ),
    }
    small = IngestionResult(
        **common,
        errors=[{"reason": "invalid", "rawRow": ["one"]}],
    )
    large = IngestionResult(
        **common,
        errors=[
            {
                "reason": "invalid",
                "rawRow": [index],
                "incomingFingerprint": f"fingerprint-{index}",
            }
            for index in range(10_000)
        ],
    )

    assert large.bounded_source_unit_result() == small.bounded_source_unit_result()
    assert "rawRow" not in str(large.bounded_source_unit_result())
    assert "fingerprint" not in str(large.bounded_source_unit_result()).lower()


@pytest.mark.asyncio
async def test_conflicting_duplicate_quarantine_preserves_row_context():
    row_processor = MagicMock()
    row_processor.process.return_value = RowOutcome(
        data_container=object(),
        ingestion_key="conflict-key",
        outcome=QualityOutcome.VALID,
        row_context={"rowNumber": 2},
    )
    batch_writer = MagicMock()
    batch_writer.submit = AsyncMock(
        return_value=[
            BatchWriteResult(
                inserted=0,
                duplicates=1,
                conflicting_duplicates=1,
                duplicate_details=[
                    DuplicateDetail(
                        identify="MOMO",
                        ingestion_key="conflict-key",
                        duplicate_type=QualityRuleCode.CONFLICTING_DUPLICATE,
                        incoming_index=0,
                        incoming_fingerprint="incoming",
                        existing_fingerprint="existing",
                        row_context={"rowNumber": 2, "rawRow": ["raw"]},
                    )
                ],
            )
        ]
    )
    batch_writer.drain = AsyncMock(return_value=[])
    quarantine = MagicMock()
    quarantine.create_many = AsyncMock(return_value=1)
    state = IngestionRunState()

    metrics = await RowBatchCoordinator(
        reader=MagicMock(iter_rows=lambda: iter([("raw",)])),
        start_row=2,
        row_processor=row_processor,
        batch_writer=batch_writer,
        state=state,
        batch_size=1,
        logger=MagicMock(),
        context=RowBatchContext(
            file_id="file-1",
            partner="MOMO",
            reconciliation_date=datetime(2026, 8, 19, tzinfo=timezone.utc),
            fetch_unit_key="unit-1",
            config_version="v1",
        ),
        quarantine_repo=quarantine,
        emit_stage=lambda _stage: None,
    ).run()

    assert metrics.db_write_count == 1
    record = quarantine.create_many.await_args.args[0][0]
    assert record.row_number == 2
    assert record.raw_row == ["raw"]
    assert record.incoming_fingerprint == "incoming"
    assert record.existing_fingerprint == "existing"
    assert state.quality_counters["conflictingDuplicateRows"] == 1


@pytest.mark.asyncio
async def test_conflict_keys_are_derived_from_the_atomic_insert_statement():
    from contextlib import asynccontextmanager

    from src.infrastructure.partner_transaction.repository import (
        DataContainerRepository,
        _PARTNER_TRANSACTION_COLUMNS,
    )

    class Record:
        def __init__(
            self,
            identify,
            ingestion_key,
            inserted_for_key,
            duplicate_count,
            inserted_count,
        ):
            self.values = (
                identify,
                ingestion_key,
                inserted_for_key,
                duplicate_count,
                inserted_count,
            )

        def __getitem__(self, key):
            if isinstance(key, int):
                return self.values[key]
            return self.values[
                {
                    "identify": 0,
                    "ingestion_key": 1,
                    "inserted_for_key": 2,
                    "duplicate_count": 3,
                    "inserted_count": 4,
                }[key]
            ]

    class Driver:
        def __init__(self):
            self.fetch_sql = ""
            self.insert_execute_calls = 0

        async def copy_records_to_table(self, *_args, **_kwargs):
            return None

        async def fetch(self, sql):
            self.fetch_sql = sql
            return [Record("MOMO", "key-1", 0, 1, 0)]

        async def execute(self, _sql):
            self.insert_execute_calls += 1
            return "INSERT 0 0"

    driver = Driver()
    raw_connection = MagicMock(driver_connection=driver)
    connection = AsyncMock()
    connection.get_raw_connection.return_value = raw_connection

    class Engine:
        @asynccontextmanager
        async def begin(self):
            yield connection

    row = {column: None for column in _PARTNER_TRANSACTION_COLUMNS}
    row.update(
        {
            "identify": "MOMO",
            "ingestion_key": "key-1",
            "partner_metadata": {},
        }
    )
    repository = DataContainerRepository(engine=Engine())

    inserted, conflict_insert_counts = await repository._insert_rows_conflict_safe([row])

    assert inserted == 0
    assert conflict_insert_counts == {("MOMO", "key-1"): 0}
    assert driver.insert_execute_calls == 0
    assert "INSERT INTO partner_transaction" in driver.fetch_sql
    assert "RETURNING identify, ingestion_key" in driver.fetch_sql
    assert "ORDER BY incoming_ordinal" in driver.fetch_sql


@pytest.mark.asyncio
async def test_batch_writer_uses_duplicate_incoming_index_for_row_context():
    from src.pipeline.batch_writer import BatchWriteCoordinator

    repository = MagicMock()
    repository.insert_many = AsyncMock(
        return_value=BatchWriteResult(
            inserted=1,
            duplicates=1,
            conflicting_duplicates=1,
            duplicate_details=[
                DuplicateDetail(
                    identify="MOMO",
                    ingestion_key="same-key",
                    duplicate_type=QualityRuleCode.CONFLICTING_DUPLICATE,
                    incoming_index=1,
                    incoming_fingerprint="incoming",
                    existing_fingerprint="existing",
                )
            ],
        )
    )
    coordinator = BatchWriteCoordinator(repository, workers=1, ordered=False)

    result = await coordinator._write(
        [
            {"ingestion_key": "same-key"},
            {"ingestion_key": "same-key"},
        ],
        [
            {"rowNumber": 10, "rawRow": ["persisted"]},
            {"rowNumber": 11, "rawRow": ["conflict"]},
        ],
    )

    assert result.duplicate_details[0].row_context == {
        "rowNumber": 11,
        "rawRow": ["conflict"],
    }


@pytest.mark.asyncio
async def test_batch_writer_calls_the_typed_port_without_legacy_flags():
    from src.pipeline.batch_writer import BatchWriteCoordinator

    class TypedWriter:
        async def insert_many(self, documents, ordered=True):
            return BatchWriteResult(inserted=len(documents))

    coordinator = BatchWriteCoordinator(TypedWriter(), workers=1, ordered=False)

    result = await coordinator.submit([{"ingestion_key": "key-1"}])

    assert result == [BatchWriteResult(inserted=1)]


@pytest.mark.asyncio
async def test_batch_writer_rejects_unbalanced_persistence_accounting():
    class InvalidWriter:
        async def insert_many(self, documents, ordered=True):
            return BatchWriteResult(inserted=1)

    coordinator = BatchWriteCoordinator(InvalidWriter(), workers=1, ordered=False)

    with pytest.raises(ValueError, match="accounting"):
        await coordinator.submit([{"ingestion_key": "key-1"}, {"ingestion_key": "key-2"}])


@pytest.mark.asyncio
async def test_batch_writer_rejects_misaligned_row_contexts():
    class TypedWriter:
        async def insert_many(self, documents, ordered=True):
            return BatchWriteResult(inserted=len(documents))

    coordinator = BatchWriteCoordinator(TypedWriter(), workers=1, ordered=False)

    with pytest.raises(ValueError, match="row context"):
        await coordinator.submit(
            [{"ingestion_key": "key-1"}, {"ingestion_key": "key-2"}],
            row_contexts=[{"rowNumber": 10}],
        )


def test_legacy_internal_quality_and_write_models_are_not_exported():
    import src.config.validator as config_validator
    import src.core.types as core_types
    import src.pipeline.row_processor as row_processor
    import src.validators.validator as validator

    assert not hasattr(core_types, "ValidationError")
    assert not hasattr(core_types, "BatchInsertResult")
    assert not hasattr(config_validator, "ConfigValidationError")
    assert not hasattr(row_processor, "RowProcessingResult")
    assert not hasattr(validator, "ValidationResult")
    assert not hasattr(validator.Validator(), "validate_with_duplicates")


def test_ingestion_package_keeps_its_existing_lazy_exports():
    import src.domain.ingestion as ingestion

    assert ingestion.IngestionOutcome.__name__ == "IngestionOutcome"
    assert ingestion.PartnerTransactionWriter.__name__ == "PartnerTransactionWriter"


def test_batch_write_result_requires_typed_duplicate_details():
    detail = DuplicateDetail(
        identify="MOMO",
        ingestion_key="key-1",
        duplicate_type=QualityRuleCode.EQUIVALENT_DUPLICATE,
        incoming_index=0,
        incoming_fingerprint="same",
        existing_fingerprint="same",
    )

    result = BatchWriteResult(
        inserted=0,
        duplicates=1,
        equivalent_duplicates=1,
        duplicate_details=[detail],
    )

    assert result.duplicate_details == [detail]
    with pytest.raises(ValueError, match="duplicate details"):
        BatchWriteResult(inserted=0, duplicates=1, equivalent_duplicates=1)

    with pytest.raises(ValueError, match="incoming indexes"):
        BatchWriteResult(
            inserted=0,
            duplicates=1,
            equivalent_duplicates=1,
            duplicate_details=[detail.model_copy(update={"incoming_index": 1})],
        )


def test_warning_is_reviewable_but_remains_persistable():
    violation = QualityViolation(
        code=QualityRuleCode.MALFORMED_ROW,
        phase=QualityPhase.VALIDATION,
        severity=QualitySeverity.WARNING,
        outcome=QualityOutcome.WARNING,
        field="metadata",
        message="Metadata was normalized with a warning.",
    )
    evaluation = QualityEvaluation(
        outcome=QualityOutcome.WARNING,
        violations=[violation],
    )
    row_outcome = RowOutcome(
        outcome=QualityOutcome.WARNING,
        violations=[violation],
        ingestion_key="key-1",
    )

    summary = QualitySummary.from_evaluations([evaluation])

    assert evaluation.is_valid is True
    assert row_outcome.is_valid is True
    assert summary.decision is QualityDecision.REVIEW
    assert orchestration_action_for(summary) is OrchestrationAction.CONTINUE

    state = IngestionRunState(total_rows=1)
    state.record_row_outcome(row_outcome)
    assert state.ingestion_keys == ["key-1"]
    assert state.warning_rows == 1
    assert state.errors[0]["errorCode"] == QualityRuleCode.MALFORMED_ROW.value


def test_quality_aggregation_never_downgrades_fail_after_a_conflict():
    state = IngestionRunState()
    state.record_quality_evaluation(
        QualityEvaluation(
            outcome=QualityOutcome.BATCH_FATAL,
            violations=[
                QualityViolation(
                    code=QualityRuleCode.CONFIG_VALIDATION,
                    phase=QualityPhase.CONFIGURATION,
                    severity=QualitySeverity.FATAL,
                    outcome=QualityOutcome.BATCH_FATAL,
                    message="Configuration is invalid.",
                )
            ],
        )
    )
    state.record_quality_evaluation(
        QualityEvaluation(
            outcome=QualityOutcome.CONFLICTING_DUPLICATE,
            violations=[
                QualityViolation(
                    code=QualityRuleCode.CONFLICTING_DUPLICATE,
                    phase=QualityPhase.PERSISTENCE,
                    severity=QualitySeverity.ERROR,
                    outcome=QualityOutcome.CONFLICTING_DUPLICATE,
                    message="Payload conflicts with the existing transaction.",
                )
            ],
        )
    )

    assert state.quality_decision is QualityDecision.FAIL
    assert state.orchestration_action is OrchestrationAction.FAIL
