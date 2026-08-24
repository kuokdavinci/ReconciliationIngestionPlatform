"""Tests for TransactionNormalizer core normalization engine."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.core.enums import TransactionStatus
from src.core.types import FieldMapping, FieldMappingType
from src.domain.ingestion.quality import (
    QualityOutcome,
    QualityPhase,
    QualityRuleCode,
    QualitySeverity,
    QualityViolation,
)
from src.normalizer import TransactionNormalizer, NormalizationResult


def _make_mapping(
    path: str,
    type: FieldMappingType,
    column: str | None = None,
    sourceField: str | None = None,
    constant: str | None = None,
) -> FieldMapping:
    """Helper to create FieldMapping instances for tests."""
    return FieldMapping(
        path=path,
        column=column,
        sourceField=sourceField,
        type=type,
        constant=constant,
    )


SAMPLE_ROW = {
    "A": "TXN001",
    "B": "100000",
    "C": "2024-01-15",
    "D": "Thành công",
}


class TestNormalizationResult:
    """Test NormalizationResult dataclass."""

    def test_empty_result(self):
        result = NormalizationResult(data={}, errors=[])
        assert result.data == {}
        assert result.errors == []

    def test_result_with_data_and_errors(self):
        err = QualityViolation(field="amount", message="invalid")
        result = NormalizationResult(
            data={"id": "TXN001"},
            errors=[err],
        )
        assert result.data == {"id": "TXN001"}
        assert len(result.errors) == 1
        assert result.errors[0].field == "amount"


class TestEmptyFieldMappings:
    """Test that empty field_mappings list is rejected."""

    def test_empty_mappings_raises_error(self):
        with pytest.raises(ValueError, match="field_mappings"):
            TransactionNormalizer(field_mappings=[])


class TestStringConversion:
    """Test STRING type conversion."""

    def test_valid_string_passthrough(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("id", FieldMappingType.STRING, column="A")]
        )
        result = normalizer.normalize({"A": "TXN001"})
        assert result.data["id"] == "TXN001"
        assert result.errors == []

    def test_numeric_value_converted_to_string(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("id", FieldMappingType.STRING, column="A")]
        )
        result = normalizer.normalize({"A": 12345})
        assert result.data["id"] == "12345"
        assert result.errors == []

    def test_none_value_produces_validation_error(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("id", FieldMappingType.STRING, column="A")]
        )
        result = normalizer.normalize({"A": None})
        assert "id" not in result.data
        assert len(result.errors) == 1
        assert result.errors[0].field == "id"

    def test_empty_string_produces_validation_error(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("id", FieldMappingType.STRING, column="A")]
        )
        result = normalizer.normalize({"A": ""})
        assert "id" not in result.data
        assert len(result.errors) == 1
        assert result.errors[0].field == "id"


class TestDecimalConversion:
    """Test DECIMAL type conversion."""

    def test_valid_integer_string_to_decimal(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("amount", FieldMappingType.DECIMAL, column="B")]
        )
        result = normalizer.normalize({"B": "100000"})
        assert result.data["amount"] == Decimal("100000")
        assert result.errors == []

    def test_valid_decimal_string_to_decimal(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("amount", FieldMappingType.DECIMAL, column="B")]
        )
        result = normalizer.normalize({"B": "99.99"})
        assert result.data["amount"] == Decimal("99.99")
        assert result.errors == []

    def test_float_input_produces_validation_error(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("amount", FieldMappingType.DECIMAL, column="B")]
        )
        result = normalizer.normalize({"B": 100.50})
        assert "amount" not in result.data
        assert len(result.errors) == 1
        assert "float" in result.errors[0].message.lower()

    def test_invalid_string_produces_validation_error(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("amount", FieldMappingType.DECIMAL, column="B")]
        )
        result = normalizer.normalize({"B": "abc"})
        assert "amount" not in result.data
        assert len(result.errors) == 1
        assert result.errors[0].field == "amount"

    @pytest.mark.parametrize("source", ["NaN", "Infinity"])
    def test_non_finite_decimal_source_produces_invalid_amount(self, source):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("amount", FieldMappingType.DECIMAL, column="B")]
        )

        result = normalizer.normalize({"B": source}, row_number=9)

        assert "amount" not in result.data
        assert [item.code for item in result.errors] == [QualityRuleCode.INVALID_AMOUNT]
        assert result.errors[0].actual is None
        assert result.errors[0].row == 9

    def test_none_value_produces_validation_error(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("amount", FieldMappingType.DECIMAL, column="B")]
        )
        result = normalizer.normalize({"B": None})
        assert "amount" not in result.data
        assert len(result.errors) == 1
        assert result.errors[0].field == "amount"


class TestDateConversion:
    """Test DATE type conversion."""

    def test_iso_timezone_timestamp_maps_to_utc_trans_date(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("transDate", FieldMappingType.DATE, column="C")]
        )

        result = normalizer.normalize(
            {"C": "2025-01-01T15:00:00+07:00"},
            row_number=9,
        )

        assert result.data["transDate"] == datetime(2025, 1, 1, 8, tzinfo=UTC)
        assert result.errors == []

    def test_invalid_timestamp_has_stable_structured_evidence(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("transDate", FieldMappingType.DATE, column="C")]
        )

        result = normalizer.normalize({"C": "not-a-timestamp"}, row_number=9)

        assert result.data == {}
        assert len(result.errors) == 1
        violation = result.errors[0]
        assert violation.code is QualityRuleCode.INVALID_TIMESTAMP
        assert violation.phase is QualityPhase.NORMALIZATION
        assert violation.severity is QualitySeverity.ERROR
        assert violation.outcome is QualityOutcome.REJECT
        assert violation.field == "transDate"
        assert violation.message == "Timestamp is not a supported date/time value."
        assert violation.expected == (
            "ISO-8601 datetime with Z/UTC offset or an approved legacy date format"
        )
        assert violation.actual == {"type": "str"}
        assert violation.row == 9

    def test_empty_timestamp_is_invalid_timestamp(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("transDate", FieldMappingType.DATE, column="C")]
        )

        result = normalizer.normalize({"C": ""}, row_number=9)

        assert [item.code for item in result.errors] == [
            QualityRuleCode.INVALID_TIMESTAMP
        ]
        assert result.errors[0].actual == {"type": "str"}

    def test_required_none_timestamp_remains_missing_required_field(self):
        normalizer = TransactionNormalizer(
            field_mappings=[
                FieldMapping(
                    path="transDate",
                    type=FieldMappingType.DATE,
                    column="C",
                    required=True,
                )
            ]
        )

        result = normalizer.normalize({"C": None}, row_number=9)

        assert [item.code for item in result.errors] == [
            QualityRuleCode.MISSING_REQUIRED_FIELD
        ]

    def test_trace_normalizes_offset_timestamp_to_utc(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("transDate", FieldMappingType.DATE, column="C")]
        )

        result, traces = normalizer.normalize_with_trace(
            {"C": "2025-01-01T15:00:00+07:00"},
            row_number=9,
        )

        assert result.errors == []
        assert traces[0].output_value == datetime(2025, 1, 1, 8, tzinfo=UTC)
        assert traces[0].error is None

    def test_iso_format_date(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("transDate", FieldMappingType.DATE, column="C")]
        )
        result = normalizer.normalize({"C": "2024-01-15"})
        assert result.data["transDate"] == datetime(2024, 1, 15)
        assert result.errors == []

    def test_dd_mm_yyyy_format_date(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("transDate", FieldMappingType.DATE, column="C")]
        )
        result = normalizer.normalize({"C": "15/01/2024"})
        assert result.data["transDate"] == datetime(2024, 1, 15)
        assert result.errors == []

    def test_iso_format_with_time(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("transDate", FieldMappingType.DATE, column="C")]
        )
        result = normalizer.normalize({"C": "2024-01-15 10:30:00"})
        assert result.data["transDate"] == datetime(2024, 1, 15, 10, 30, 0)
        assert result.errors == []

    def test_dd_mm_yyyy_with_time(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("transDate", FieldMappingType.DATE, column="C")]
        )
        result = normalizer.normalize({"C": "15/01/2024 10:30:00"})
        assert result.data["transDate"] == datetime(2024, 1, 15, 10, 30, 0)
        assert result.errors == []

    def test_datetime_passed_through_as_is(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("transDate", FieldMappingType.DATE, column="C")]
        )
        original = datetime(2024, 3, 20)
        result = normalizer.normalize({"C": original})
        assert result.data["transDate"] is original
        assert result.errors == []

    def test_invalid_string_produces_validation_error(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("transDate", FieldMappingType.DATE, column="C")]
        )
        result = normalizer.normalize({"C": "not-a-date"})
        assert "transDate" not in result.data
        assert len(result.errors) == 1
        assert result.errors[0].field == "transDate"

    def test_none_value_produces_validation_error(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("transDate", FieldMappingType.DATE, column="C")]
        )
        result = normalizer.normalize({"C": None})
        assert "transDate" not in result.data
        assert len(result.errors) == 1
        assert result.errors[0].field == "transDate"


class TestConstantConversion:
    """Test CONSTANT type conversion."""

    def test_valid_constant_returned(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("currency", FieldMappingType.CONSTANT, constant="VND")]
        )
        result = normalizer.normalize({})
        assert result.data["currency"] == "VND"
        assert result.errors == []

    def test_none_constant_produces_error(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("currency", FieldMappingType.CONSTANT, constant=None)]
        )
        result = normalizer.normalize({})
        assert "currency" not in result.data
        assert len(result.errors) == 1
        assert result.errors[0].field == "currency"


class TestSourceFieldResolution:
    """Test source field resolution by column and sourceField."""

    def test_resolve_by_column_letter(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("id", FieldMappingType.STRING, column="A")]
        )
        result = normalizer.normalize({"A": "TXN001"})
        assert result.data["id"] == "TXN001"

    def test_resolve_by_source_field(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("id", FieldMappingType.STRING, sourceField="txn_id")]
        )
        result = normalizer.normalize({"txn_id": "TXN002"})
        assert result.data["id"] == "TXN002"

    def test_column_takes_precedence_over_source_field(self):
        normalizer = TransactionNormalizer(
            field_mappings=[
                _make_mapping("id", FieldMappingType.STRING, column="A", sourceField="txn_id")
            ]
        )
        result = normalizer.normalize({"A": "FROM_COL", "txn_id": "FROM_SOURCE"})
        assert result.data["id"] == "FROM_COL"

    def test_missing_column_key_produces_error(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("id", FieldMappingType.STRING, column="Z")]
        )
        result = normalizer.normalize({"A": "TXN001"})
        assert "id" not in result.data
        assert len(result.errors) == 1
        assert "not found" in result.errors[0].message.lower()

    def test_missing_source_field_key_produces_error(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("id", FieldMappingType.STRING, sourceField="missing_key")]
        )
        result = normalizer.normalize({"A": "TXN001"})
        assert "id" not in result.data
        assert len(result.errors) == 1
        assert "not found" in result.errors[0].message.lower()

    def test_no_column_and_no_source_field_produces_error(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("id", FieldMappingType.STRING)]
        )
        result = normalizer.normalize({"A": "TXN001"})
        assert "id" not in result.data
        assert len(result.errors) == 1
        assert "no column" in result.errors[0].message.lower()

    def test_constant_skips_row_lookup(self):
        normalizer = TransactionNormalizer(
            field_mappings=[_make_mapping("currency", FieldMappingType.CONSTANT, constant="VND")]
        )
        # Empty row — should still work for CONSTANT
        result = normalizer.normalize({})
        assert result.data["currency"] == "VND"
        assert result.errors == []


class TestErrorCollection:
    """Test that multiple errors are collected (not fail-fast)."""

    def test_multiple_errors_collected(self):
        normalizer = TransactionNormalizer(
            field_mappings=[
                _make_mapping("id", FieldMappingType.STRING, column="A"),
                _make_mapping("amount", FieldMappingType.DECIMAL, column="B"),
                _make_mapping("transDate", FieldMappingType.DATE, column="C"),
            ]
        )
        result = normalizer.normalize({"A": None, "B": "abc", "C": "not-a-date"})
        assert len(result.errors) == 3
        assert result.data == {}

    def test_successful_fields_in_data_with_other_errors(self):
        normalizer = TransactionNormalizer(
            field_mappings=[
                _make_mapping("id", FieldMappingType.STRING, column="A"),
                _make_mapping("amount", FieldMappingType.DECIMAL, column="B"),
            ]
        )
        result = normalizer.normalize({"A": "TXN001", "B": "abc"})
        assert result.data["id"] == "TXN001"
        assert "amount" not in result.data
        assert len(result.errors) == 1

    def test_row_number_propagated_to_errors(self):
        normalizer = TransactionNormalizer(
            field_mappings=[
                _make_mapping("id", FieldMappingType.STRING, column="A"),
                _make_mapping("amount", FieldMappingType.DECIMAL, column="B"),
            ]
        )
        result = normalizer.normalize({"A": None, "B": None}, row_number=42)
        assert len(result.errors) == 2
        for err in result.errors:
            assert err.row == 42


class TestFullNormalization:
    """Test full normalization with multiple field types."""

    def test_full_sample_row(self):
        normalizer = TransactionNormalizer(
            field_mappings=[
                _make_mapping("id", FieldMappingType.STRING, column="A"),
                _make_mapping("amount", FieldMappingType.DECIMAL, column="B"),
                _make_mapping("transDate", FieldMappingType.DATE, column="C"),
                _make_mapping("currency", FieldMappingType.CONSTANT, constant="VND"),
            ]
        )
        result = normalizer.normalize(SAMPLE_ROW)
        assert result.data["id"] == "TXN001"
        assert result.data["amount"] == Decimal("100000")
        assert result.data["currency"] == "VND"
        assert result.errors == []


class TestMappingConversion:
    """Test MAPPING type conversion with 'others' fallback."""

    def _make_mapping_with_dict(
        self,
        path: str,
        mapping: dict[str, str],
        column: str | None = None,
    ) -> FieldMapping:
        """Helper to create FieldMapping with mapping dict."""
        return FieldMapping(
            path=path,
            column=column,
            type=FieldMappingType.MAPPING,
            mapping=mapping,
        )

    def test_known_value_mapped_correctly(self):
        """Known value 'Thành công' → 'SUCCESS'."""
        fm = self._make_mapping_with_dict(
            "status",
            mapping={"Thành công": "SUCCESS", "Thất bại": "FAILED", "others": "FAILED"},
            column="D",
        )
        value, error = TransactionNormalizer._convert_mapping("Thành công", fm)
        assert value == "SUCCESS"
        assert error is None

    def test_known_value_failed_mapped(self):
        """Known value 'Thất bại' → 'FAILED'."""
        fm = self._make_mapping_with_dict(
            "status",
            mapping={"Thành công": "SUCCESS", "Thất bại": "FAILED", "others": "FAILED"},
            column="D",
        )
        value, error = TransactionNormalizer._convert_mapping("Thất bại", fm)
        assert value == "FAILED"
        assert error is None

    def test_unknown_value_with_others_fallback(self):
        """Unknown value 'Bất kỳ' → 'FAILED' via 'others' key."""
        fm = self._make_mapping_with_dict(
            "status",
            mapping={"Thành công": "SUCCESS", "Thất bại": "FAILED", "others": "FAILED"},
            column="D",
        )
        value, error = TransactionNormalizer._convert_mapping("Bất kỳ", fm)
        assert value == "FAILED"
        assert error is None

    def test_unknown_value_without_others_produces_error(self):
        """Unknown value 'X' without 'others' key → QualityViolation."""
        fm = self._make_mapping_with_dict(
            "status",
            mapping={"Thành công": "SUCCESS", "Thất bại": "FAILED"},
            column="D",
        )
        value, error = TransactionNormalizer._convert_mapping("X", fm)
        assert value is None
        assert error is not None
        assert isinstance(error, QualityViolation)
        assert "unmapped value" in error.message
        assert "X" in error.message

    def test_none_value_produces_error(self):
        """None value → QualityViolation."""
        fm = self._make_mapping_with_dict(
            "status",
            mapping={"Thành công": "SUCCESS", "others": "FAILED"},
            column="D",
        )
        value, error = TransactionNormalizer._convert_mapping(None, fm)
        assert value is None
        assert error is not None
        assert isinstance(error, QualityViolation)
        assert "empty" in error.message.lower() or "null" in error.message.lower()

    def test_empty_string_produces_error(self):
        """Empty string value → QualityViolation."""
        fm = self._make_mapping_with_dict(
            "status",
            mapping={"Thành công": "SUCCESS", "others": "FAILED"},
            column="D",
        )
        value, error = TransactionNormalizer._convert_mapping("", fm)
        assert value is None
        assert error is not None
        assert isinstance(error, QualityViolation)
        assert "empty" in error.message.lower() or "null" in error.message.lower()

    def test_numeric_value_converted_to_string_before_lookup(self):
        """Numeric value 1 → str '1' → lookup in mapping."""
        fm = self._make_mapping_with_dict(
            "status",
            mapping={"1": "SUCCESS", "0": "FAILED", "others": "FAILED"},
            column="D",
        )
        value, error = TransactionNormalizer._convert_mapping(1, fm)
        assert value == "SUCCESS"
        assert error is None

    def test_row_number_propagated_to_error(self):
        """Row number included in QualityViolation."""
        fm = self._make_mapping_with_dict(
            "status",
            mapping={"Thành công": "SUCCESS"},
            column="D",
        )
        value, error = TransactionNormalizer._convert_mapping("Unknown", fm, row_number=5)
        assert error is not None
        assert error.row == 5

    def test_mapping_with_status_field_None_value(self):
        """MAPPING field with None source value produces QualityViolation with 'empty' or 'null'."""
        fm = self._make_mapping_with_dict(
            "status",
            mapping={"Thành công": "SUCCESS", "Thất bại": "FAILED", "others": "FAILED"},
            column="D",
        )
        value, error = TransactionNormalizer._convert_mapping(None, fm)
        assert value is None
        assert error is not None
        assert isinstance(error, QualityViolation)
        assert "empty" in error.message.lower() or "null" in error.message.lower()

    def test_mapping_with_unknown_value_no_others_case_insensitive(self):
        """Unknown status value without 'others' fallback produces QualityViolation."""
        fm = self._make_mapping_with_dict(
            "status",
            mapping={"Thành công": "SUCCESS", "Thất bại": "FAILED"},
            column="D",
        )
        value, error = TransactionNormalizer._convert_mapping("unknown_status", fm)
        assert value is None
        assert error is not None
        assert isinstance(error, QualityViolation)
        assert "unmapped value" in error.message


class TestBuildCanonical:
    """Test CanonicalTransaction construction from normalized data."""

    def test_all_required_fields_produces_transaction(self):
        """All required fields → CanonicalTransaction with correct types."""
        data = {
            "id": "TXN001",
            "amount": Decimal("100000"),
            "currency": "VND",
            "status": "SUCCESS",
        }
        errors: list[QualityViolation] = []
        txn, errors = TransactionNormalizer.build_canonical(data, errors)
        assert txn is not None
        assert txn.id == "TXN001"
        assert txn.amount == Decimal("100000")
        assert txn.currency == "VND"
        assert txn.status == TransactionStatus.SUCCESS
        assert errors == []

    def test_missing_id_produces_error(self):
        """Missing 'id' → QualityViolation."""
        data = {
            "amount": Decimal("100000"),
            "currency": "VND",
            "status": "SUCCESS",
        }
        errors: list[QualityViolation] = []
        txn, errors = TransactionNormalizer.build_canonical(data, errors)
        assert txn is None
        assert len(errors) == 1
        assert errors[0].field == "id"

    def test_missing_amount_produces_error(self):
        """Missing 'amount' → QualityViolation."""
        data = {
            "id": "TXN001",
            "currency": "VND",
            "status": "SUCCESS",
        }
        errors: list[QualityViolation] = []
        txn, errors = TransactionNormalizer.build_canonical(data, errors)
        assert txn is None
        assert len(errors) == 1
        assert errors[0].field == "amount"

    def test_missing_currency_produces_error(self):
        """Missing 'currency' → QualityViolation."""
        data = {
            "id": "TXN001",
            "amount": Decimal("100000"),
            "status": "SUCCESS",
        }
        errors: list[QualityViolation] = []
        txn, errors = TransactionNormalizer.build_canonical(data, errors)
        assert txn is None
        assert len(errors) == 1
        assert errors[0].field == "currency"

    def test_missing_status_produces_error(self):
        """Missing 'status' → QualityViolation."""
        data = {
            "id": "TXN001",
            "amount": Decimal("100000"),
            "currency": "VND",
        }
        errors: list[QualityViolation] = []
        txn, errors = TransactionNormalizer.build_canonical(data, errors)
        assert txn is None
        assert len(errors) == 1
        assert errors[0].field == "status"

    def test_multiple_missing_fields_produce_multiple_errors(self):
        """Missing 'id' and 'amount' → 2 QualityViolations."""
        data = {
            "currency": "VND",
            "status": "SUCCESS",
        }
        errors: list[QualityViolation] = []
        txn, errors = TransactionNormalizer.build_canonical(data, errors)
        assert txn is None
        assert len(errors) == 2
        fields = {e.field for e in errors}
        assert "id" in fields
        assert "amount" in fields

    def test_invalid_status_string_produces_error(self):
        """Invalid status 'UNKNOWN' → QualityViolation."""
        data = {
            "id": "TXN001",
            "amount": Decimal("100000"),
            "currency": "VND",
            "status": "UNKNOWN",
        }
        errors: list[QualityViolation] = []
        txn, errors = TransactionNormalizer.build_canonical(data, errors)
        assert txn is None
        assert len(errors) == 1
        assert errors[0].field == "status"
        assert "invalid status" in errors[0].message.lower()

    def test_valid_status_converted_to_enum(self):
        """Valid status 'SUCCESS' → TransactionStatus.SUCCESS enum."""
        data = {
            "id": "TXN001",
            "amount": Decimal("100000"),
            "currency": "VND",
            "status": "SUCCESS",
        }
        errors: list[QualityViolation] = []
        txn, errors = TransactionNormalizer.build_canonical(data, errors)
        assert txn is not None
        assert txn.status is TransactionStatus.SUCCESS
        assert isinstance(txn.status, TransactionStatus)

    def test_optional_trace_included_when_present(self):
        """Optional 'trace' field included in transaction."""
        data = {
            "id": "TXN001",
            "trace": "REF123",
            "amount": Decimal("100000"),
            "currency": "VND",
            "status": "SUCCESS",
        }
        errors: list[QualityViolation] = []
        txn, errors = TransactionNormalizer.build_canonical(data, errors)
        assert txn is not None
        assert txn.trace == "REF123"

    def test_optional_trans_date_included_when_present(self):
        """Optional 'transDate' field included in transaction."""
        dt = datetime(2024, 1, 15)
        data = {
            "id": "TXN001",
            "amount": Decimal("100000"),
            "currency": "VND",
            "status": "SUCCESS",
            "transDate": dt,
        }
        errors: list[QualityViolation] = []
        txn, errors = TransactionNormalizer.build_canonical(data, errors)
        assert txn is not None
        assert txn.transDate == dt

    def test_extra_fields_placed_in_extra_dict(self):
        """Fields not in CanonicalTransaction schema → extra dict."""
        data = {
            "id": "TXN001",
            "amount": Decimal("100000"),
            "currency": "VND",
            "status": "SUCCESS",
            "partnerCode": "VN001",
            "batchId": "BATCH1",
        }
        errors: list[QualityViolation] = []
        txn, errors = TransactionNormalizer.build_canonical(data, errors)
        assert txn is not None
        assert txn.extra == {"partnerCode": "VN001", "batchId": "BATCH1"}

    def test_pre_existing_errors_passed_through(self):
        """Pre-existing errors not cleared."""
        data = {
            "id": "TXN001",
            "amount": Decimal("100000"),
            "currency": "VND",
            "status": "SUCCESS",
        }
        existing_error = QualityViolation(field="amount", message="pre-existing error")
        errors: list[QualityViolation] = [existing_error]
        txn, errors = TransactionNormalizer.build_canonical(data, errors)
        assert txn is not None
        assert len(errors) == 1
        assert errors[0].message == "pre-existing error"

    def test_row_number_propagated_to_error(self):
        """Row number included in QualityViolation."""
        data = {"amount": Decimal("100000"), "currency": "VND", "status": "SUCCESS"}
        errors: list[QualityViolation] = []
        txn, errors = TransactionNormalizer.build_canonical(data, errors, row_number=10)
        assert txn is None
        assert errors[0].row == 10


class TestFullIntegration:
    """End-to-end: normalize() + build_canonical() integration."""

    def test_end_to_end_successful_row(self):
        """Raw row → normalize() → build_canonical() → CanonicalTransaction."""
        field_mappings = [
            FieldMapping(path="id", column="A", type=FieldMappingType.STRING),
            FieldMapping(path="trace", column="B", type=FieldMappingType.STRING),
            FieldMapping(path="amount", column="C", type=FieldMappingType.DECIMAL),
            FieldMapping(path="currency", type=FieldMappingType.CONSTANT, constant="VND"),
            FieldMapping(
                path="status",
                column="D",
                type=FieldMappingType.MAPPING,
                mapping={"Thành công": "SUCCESS", "Thất bại": "FAILED", "others": "FAILED"},
            ),
            FieldMapping(path="transDate", column="E", type=FieldMappingType.DATE),
        ]

        row = {
            "A": "TXN20240115001",
            "B": "REF123456",
            "C": "1500000",
            "D": "Thành công",
            "E": "15/01/2024",
        }

        normalizer = TransactionNormalizer(field_mappings)
        result = normalizer.normalize(row, row_number=5)
        txn, errors = TransactionNormalizer.build_canonical(
            result.data, result.errors, row_number=5
        )

        assert txn is not None
        assert txn.id == "TXN20240115001"
        assert txn.trace == "REF123456"
        assert txn.amount == Decimal("1500000")
        assert txn.currency == "VND"
        assert txn.status == TransactionStatus.SUCCESS
        assert txn.transDate == datetime(2024, 1, 15)
        assert errors == []

    def test_end_to_end_row_with_mapping_errors(self):
        """Row with unmapped status → NormalizationResult with errors, no transaction."""
        field_mappings = [
            FieldMapping(path="id", column="A", type=FieldMappingType.STRING),
            FieldMapping(path="amount", column="C", type=FieldMappingType.DECIMAL),
            FieldMapping(path="currency", type=FieldMappingType.CONSTANT, constant="VND"),
            FieldMapping(
                path="status",
                column="D",
                type=FieldMappingType.MAPPING,
                mapping={"Thành công": "SUCCESS", "Thất bại": "FAILED"},
                # No "others" key — unknown status produces error
            ),
        ]

        row = {
            "A": "TXN002",
            "C": "500000",
            "D": "Đang xử lý",  # Not in mapping, no "others"
        }

        normalizer = TransactionNormalizer(field_mappings)
        result = normalizer.normalize(row, row_number=3)
        txn, errors = TransactionNormalizer.build_canonical(
            result.data, result.errors, row_number=3
        )

        assert txn is None
        assert len(errors) >= 1
        assert any(e.field == "status" for e in errors)

    def test_end_to_end_partial_errors(self):
        """Row with some valid fields and some invalid → errors collected."""
        field_mappings = [
            FieldMapping(path="id", column="A", type=FieldMappingType.STRING),
            FieldMapping(path="amount", column="C", type=FieldMappingType.DECIMAL),
            FieldMapping(path="currency", type=FieldMappingType.CONSTANT, constant="VND"),
            FieldMapping(
                path="status",
                column="D",
                type=FieldMappingType.MAPPING,
                mapping={"Thành công": "SUCCESS", "others": "FAILED"},
            ),
        ]

        row = {
            "A": "TXN003",
            "C": "not-a-number",  # Invalid decimal
            "D": "Thành công",  # Valid mapping
        }

        normalizer = TransactionNormalizer(field_mappings)
        result = normalizer.normalize(row, row_number=7)
        txn, errors = TransactionNormalizer.build_canonical(
            result.data, result.errors, row_number=7
        )

        # id and status normalized, amount failed → missing amount in build_canonical
        assert txn is None
        assert len(errors) >= 1
        assert any(e.field == "amount" for e in errors)
        assert result.data.get("id") == "TXN003"
        assert result.data.get("status") == "SUCCESS"

    def test_realistic_vietnamese_partner_data(self):
        """Realistic Vietnamese bank settlement row with all fields."""
        field_mappings = [
            FieldMapping(path="id", column="A", type=FieldMappingType.STRING),
            FieldMapping(path="trace", column="B", type=FieldMappingType.STRING),
            FieldMapping(path="amount", column="C", type=FieldMappingType.DECIMAL),
            FieldMapping(path="currency", type=FieldMappingType.CONSTANT, constant="VND"),
            FieldMapping(
                path="status",
                column="D",
                type=FieldMappingType.MAPPING,
                mapping={
                    "Thành công": "SUCCESS",
                    "Thất bại": "FAILED",
                    "Đang xử lý": "PENDING",
                    "others": "FAILED",
                },
            ),
            FieldMapping(path="transDate", column="E", type=FieldMappingType.DATE),
        ]

        row = {
            "A": "TXN20240115001",
            "B": "REF123456",
            "C": "1500000",
            "D": "Thành công",
            "E": "15/01/2024",
        }

        normalizer = TransactionNormalizer(field_mappings)
        result = normalizer.normalize(row, row_number=5)
        txn, errors = TransactionNormalizer.build_canonical(
            result.data, result.errors, row_number=5
        )

        assert txn is not None
        assert txn.id == "TXN20240115001"
        assert txn.trace == "REF123456"
        assert txn.amount == Decimal("1500000")
        assert txn.currency == "VND"
        assert txn.status == TransactionStatus.SUCCESS
        assert txn.transDate == datetime(2024, 1, 15)
        assert errors == []
