"""Tests for core enums, constants, and canonical types."""

from decimal import Decimal
import pytest

from src.core.enums import ProcessingStatus, TransactionStatus, FileType
from src.core.constants import (
    DUPLICATE_KEY_PATTERN,
    DEFAULT_CURRENCY,
    MAX_FILE_SIZE_MB,
    FILE_HASH_KEY,
    LOG_FORMATS,
)
from src.core.types import (
    FieldMappingType,
    FieldMapping,
    CanonicalTransaction,
    PartnerData,
    ValidationError,
    ProcessingStats,
)


class TestProcessingStatus:
    """Test ProcessingStatus enum values."""

    def test_has_pending(self):
        assert ProcessingStatus.PENDING == "PENDING"

    def test_has_processing(self):
        assert ProcessingStatus.PROCESSING == "PROCESSING"

    def test_has_completed(self):
        assert ProcessingStatus.COMPLETED == "COMPLETED"

    def test_has_failed(self):
        assert ProcessingStatus.FAILED == "FAILED"

    def test_is_str_enum(self):
        assert isinstance(ProcessingStatus.PENDING, str)


class TestTransactionStatus:
    """Test TransactionStatus enum values."""

    def test_has_success(self):
        assert TransactionStatus.SUCCESS == "SUCCESS"

    def test_has_failed(self):
        assert TransactionStatus.FAILED == "FAILED"

    def test_has_pending(self):
        assert TransactionStatus.PENDING == "PENDING"

    def test_has_reversed(self):
        assert TransactionStatus.REVERSED == "REVERSED"

    def test_is_str_enum(self):
        assert isinstance(TransactionStatus.SUCCESS, str)


class TestFileType:
    """Test FileType enum values."""

    def test_has_settlement(self):
        assert FileType.SETTLEMENT == "SETTLEMENT"

    def test_has_reconciliation(self):
        assert FileType.RECONCILIATION == "RECONCILIATION"

    def test_is_str_enum(self):
        assert isinstance(FileType.SETTLEMENT, str)


class TestFieldMappingType:
    """Test FieldMappingType enum values."""

    def test_has_string(self):
        assert FieldMappingType.STRING == "STRING"

    def test_has_decimal(self):
        assert FieldMappingType.DECIMAL == "DECIMAL"

    def test_has_date(self):
        assert FieldMappingType.DATE == "DATE"

    def test_has_constant(self):
        assert FieldMappingType.CONSTANT == "CONSTANT"

    def test_has_mapping(self):
        assert FieldMappingType.MAPPING == "MAPPING"


class TestConstants:
    """Test module constants."""

    def test_duplicate_key_pattern(self):
        assert "reconciliationDate" in DUPLICATE_KEY_PATTERN
        assert "trace" in DUPLICATE_KEY_PATTERN

    def test_default_currency(self):
        assert DEFAULT_CURRENCY == "VND"

    def test_max_file_size(self):
        assert MAX_FILE_SIZE_MB == 50

    def test_file_hash_key(self):
        assert FILE_HASH_KEY == "fileHash"

    def test_log_formats(self):
        assert "json" in LOG_FORMATS
        assert "text" in LOG_FORMATS


class TestCanonicalTransaction:
    """Test CanonicalTransaction model."""

    def test_create_with_valid_data(self):
        txn = CanonicalTransaction(
            id="TXN-001",
            amount=Decimal("100.50"),
            currency="VND",
            status=TransactionStatus.SUCCESS,
        )
        assert txn.id == "TXN-001"
        assert txn.amount == Decimal("100.50")
        assert txn.currency == "VND"
        assert txn.status == TransactionStatus.SUCCESS

    def test_amount_is_decimal(self):
        txn = CanonicalTransaction(
            id="TXN-002",
            amount=Decimal("200.00"),
            currency="USD",
            status=TransactionStatus.SUCCESS,
        )
        assert isinstance(txn.amount, Decimal)

    def test_amount_from_string(self):
        """CanonicalTransaction should accept string and convert to Decimal."""
        txn = CanonicalTransaction(
            id="TXN-003",
            amount="150.75",
            currency="VND",
            status=TransactionStatus.SUCCESS,
        )
        assert txn.amount == Decimal("150.75")

    def test_amount_from_int(self):
        """CanonicalTransaction should accept int and convert to Decimal."""
        txn = CanonicalTransaction(
            id="TXN-004",
            amount=1000,
            currency="VND",
            status=TransactionStatus.SUCCESS,
        )
        assert txn.amount == Decimal("1000")

    def test_rejects_float_amount(self):
        """CanonicalTransaction should reject float for amount."""
        with pytest.raises((ValueError, TypeError)):
            CanonicalTransaction(
                id="TXN-005",
                amount=100.50,  # float — should be rejected
                currency="VND",
                status=TransactionStatus.SUCCESS,
            )

    def test_required_fields(self):
        """id, amount, currency, status are required."""
        with pytest.raises(Exception):
            CanonicalTransaction(
                amount=Decimal("100"),
                currency="VND",
                status=TransactionStatus.SUCCESS,
            )

    def test_optional_fields(self):
        txn = CanonicalTransaction(
            id="TXN-006",
            amount=Decimal("100"),
            currency="VND",
            status=TransactionStatus.SUCCESS,
        )
        assert txn.trace is None
        assert txn.transDate is None
        assert txn.extra == {}

    def test_extra_field(self):
        txn = CanonicalTransaction(
            id="TXN-007",
            amount=Decimal("100"),
            currency="VND",
            status=TransactionStatus.SUCCESS,
            extra={"partner": "ABC", "notes": "test"},
        )
        assert txn.extra["partner"] == "ABC"


class TestFieldMapping:
    """Test FieldMapping model."""

    def test_column_mapping(self):
        m = FieldMapping(
            path="amount",
            column="B",
            type=FieldMappingType.DECIMAL,
        )
        assert m.path == "amount"
        assert m.column == "B"
        assert m.type == FieldMappingType.DECIMAL

    def test_constant_mapping(self):
        m = FieldMapping(
            path="currency",
            type=FieldMappingType.CONSTANT,
            constant="VND",
        )
        assert m.constant == "VND"

    def test_mapping_type(self):
        m = FieldMapping(
            path="status",
            sourceField="status_code",
            type=FieldMappingType.MAPPING,
            mapping={"1": "SUCCESS", "0": "FAILED"},
        )
        assert m.mapping["1"] == "SUCCESS"

    def test_required_flag(self):
        m = FieldMapping(
            path="id",
            column="A",
            type=FieldMappingType.STRING,
            required=True,
        )
        assert m.required is True


class TestValidationError:
    """Test ValidationError model."""

    def test_required_fields(self):
        err = ValidationError(field="amount", reason="invalid decimal")
        assert err.field == "amount"
        assert err.reason == "invalid decimal"

    def test_optional_row(self):
        err = ValidationError(field="amount", reason="invalid", row=42)
        assert err.row == 42

    def test_optional_trace(self):
        err = ValidationError(field="id", reason="missing", trace="TXN-001")
        assert err.trace == "TXN-001"

    def test_serialization(self):
        err = ValidationError(field="amount", reason="invalid", row=10)
        data = err.model_dump()
        assert data["field"] == "amount"
        assert data["reason"] == "invalid"
        assert data["row"] == 10


class TestPartnerData:
    """Test PartnerData model."""

    def test_create_with_valid_data(self):
        data = PartnerData(
            id="P-001",
            status="SUCCESS",
            amount=Decimal("500.00"),
            currency="VND",
        )
        assert data.id == "P-001"
        assert data.amount == Decimal("500.00")

    def test_optional_fields(self):
        data = PartnerData(
            id="P-002",
            status="PENDING",
            amount=Decimal("100"),
            currency="USD",
        )
        assert data.trace is None
        assert data.transDate is None
        assert data.extra == {}


class TestProcessingStats:
    """Test ProcessingStats model."""

    def test_create_stats(self):
        stats = ProcessingStats(total_rows=100, success_rows=95, failed_rows=5)
        assert stats.total_rows == 100
        assert stats.success_rows == 95
        assert stats.failed_rows == 5
