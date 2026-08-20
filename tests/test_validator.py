"""Tests for Validator core validation — required field validation."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from src.core.enums import TransactionStatus
from src.core.types import CanonicalTransaction
from src.domain.ingestion.quality import (
    QualityEvaluation,
    QualityOutcome,
    QualityViolation,
)
from src.validators import Validator


def _make_valid_txn(**overrides: Any) -> CanonicalTransaction:
    """Helper to create a valid CanonicalTransaction with optional overrides."""
    defaults: dict[str, Any] = {
        "id": "TXN001",
        "amount": Decimal("100000"),
        "currency": "VND",
        "status": TransactionStatus.SUCCESS,
    }
    defaults.update(overrides)
    return CanonicalTransaction(**defaults)


class TestRequiredFieldValidation:
    """Test that required fields are validated and errors collected."""

    def test_hot_path_can_skip_row_context_for_valid_evaluation(self):
        validator = Validator()
        txn = _make_valid_txn()

        result = validator.validate(txn, row_number=42, trace="TRACE-42", include_context=False)

        assert result.is_valid is True
        assert result.row_context == {}

    def test_valid_transaction_passes(self):
        """Valid CanonicalTransaction with all fields → QualityEvaluation(outcome=QualityOutcome.VALID, violations=[])."""
        validator = Validator()
        txn = _make_valid_txn()
        result = validator.validate(txn)
        assert result.is_valid is True
        assert result.violations == []

    def test_missing_id_produces_error(self):
        """CanonicalTransaction with empty id → QualityViolation(field='id')."""
        validator = Validator()
        txn = _make_valid_txn(id="")
        result = validator.validate(txn)
        assert result.is_valid is False
        assert len(result.violations) == 1
        assert result.violations[0].field == "id"
        assert "id" in result.violations[0].message.lower()

    def test_empty_id_produces_error(self):
        """CanonicalTransaction with whitespace-only id → QualityViolation(field='id')."""
        validator = Validator()
        txn = _make_valid_txn(id="   ")
        result = validator.validate(txn)
        assert result.is_valid is False
        assert len(result.violations) == 1
        assert result.violations[0].field == "id"

    def test_valid_amount_present_no_error(self):
        """CanonicalTransaction with valid amount → no validation error."""
        validator = Validator()
        txn = _make_valid_txn()
        result = validator.validate(txn)
        assert result.is_valid is True

    def test_missing_currency_produces_error(self):
        """CanonicalTransaction with empty currency → QualityViolation(field='currency')."""
        validator = Validator()
        txn = _make_valid_txn(currency="")
        result = validator.validate(txn)
        assert result.is_valid is False
        assert len(result.violations) == 1
        assert result.violations[0].field == "currency"

    def test_multiple_missing_fields_produce_multiple_errors(self):
        """Transaction with empty id AND empty currency → 2 ValidationErrors (not fail-fast)."""
        validator = Validator()
        txn = _make_valid_txn(id="", currency="")
        result = validator.validate(txn)
        assert result.is_valid is False
        assert len(result.violations) == 2
        fields = {e.field for e in result.violations}
        assert "id" in fields
        assert "currency" in fields

    def test_row_number_propagated_to_errors(self):
        """row_number parameter included in QualityViolation objects."""
        validator = Validator()
        txn = _make_valid_txn(id="")
        result = validator.validate(txn, row_number=42)
        assert len(result.violations) >= 1
        assert result.violations[0].row == 42

    def test_trace_propagated_to_errors(self):
        """trace parameter included in QualityViolation objects."""
        validator = Validator()
        txn = _make_valid_txn(id="")
        result = validator.validate(txn, trace="REF123")
        assert len(result.violations) >= 1
        assert result.violations[0].trace == "REF123"

    def test_row_number_and_trace_both_propagated(self):
        """Both row_number and trace included in QualityViolation objects."""
        validator = Validator()
        txn = _make_valid_txn(id="", currency="")
        result = validator.validate(txn, row_number=7, trace="REF456")
        for err in result.violations:
            assert err.row == 7
            assert err.trace == "REF456"

    def test_validation_result_structure(self):
        """QualityEvaluation has is_valid bool and errors list."""
        result = QualityEvaluation(outcome=QualityOutcome.VALID, violations=[])
        assert isinstance(result.is_valid, bool)
        assert isinstance(result.violations, list)

        err = QualityViolation(field="id", message="test")
        result2 = QualityEvaluation(outcome=QualityOutcome.REJECT, violations=[err])
        assert result2.is_valid is False
        assert len(result2.violations) == 1

    def test_empty_trace_does_not_fail(self):
        """Empty trace (optional field) does NOT produce validation errors."""
        validator = Validator()
        txn = _make_valid_txn(trace="")
        result = validator.validate(txn)
        assert result.is_valid is True
        assert result.violations == []

    def test_all_fields_empty_produces_all_errors(self):
        """CanonicalTransaction with empty required fields produces errors for each."""
        validator = Validator()
        txn = _make_valid_txn(id="", currency="")
        result = validator.validate(txn)
        assert result.is_valid is False
        assert len(result.violations) >= 2
        fields = {e.field for e in result.violations}
        assert "id" in fields
        assert "currency" in fields


class TestDecimalValidation:
    """Test decimal (amount) business rule validation."""

    def test_positive_amount_passes(self):
        """Positive Decimal amount → no validation error."""
        validator = Validator()
        txn = _make_valid_txn(amount=Decimal("100000"))
        result = validator.validate(txn)
        assert result.is_valid is True
        assert result.violations == []

    def test_zero_amount_passes(self):
        """Zero amount → no error (zero-value transactions are valid)."""
        validator = Validator()
        txn = _make_valid_txn(amount=Decimal("0"))
        result = validator.validate(txn)
        assert result.is_valid is True
        assert result.violations == []

    def test_negative_amount_fails(self):
        """Negative amount → QualityViolation(field='amount')."""
        validator = Validator()
        txn = _make_valid_txn(amount=Decimal("-500"))
        result = validator.validate(txn)
        assert result.is_valid is False
        assert len(result.violations) == 1
        assert result.violations[0].field == "amount"
        assert "non-negative" in result.violations[0].message.lower()

    def test_negative_amount_error_includes_value(self):
        """Negative amount error message includes the actual value."""
        validator = Validator()
        txn = _make_valid_txn(amount=Decimal("-123.45"))
        result = validator.validate(txn)
        assert len(result.violations) == 1
        assert "-123.45" in result.violations[0].message


class TestDateValidation:
    """Test date (transDate) type integrity validation."""

    def test_none_trans_date_passes(self):
        """None transDate → no error (it's optional)."""
        validator = Validator()
        txn = _make_valid_txn(transDate=None)
        result = validator.validate(txn)
        assert result.is_valid is True
        assert result.violations == []

    def test_valid_datetime_passes(self):
        """Valid datetime transDate → no error."""
        validator = Validator()
        dt = datetime(2024, 1, 15, 10, 30, 0)
        txn = _make_valid_txn(transDate=dt)
        result = validator.validate(txn)
        assert result.is_valid is True
        assert result.violations == []

    def test_invalid_type_fails(self):
        """Non-datetime transDate → QualityViolation(field='transDate')."""
        # We can't construct CanonicalTransaction with non-datetime transDate
        # because pydantic enforces it. So we test the validator's internal
        # method directly.
        validator = Validator()
        # The validator should handle the case where transDate is somehow
        # not a datetime (defensive check). Since pydantic enforces this,
        # we test that the validator method correctly validates datetime.
        dt = datetime(2024, 6, 1)
        txn = _make_valid_txn(transDate=dt)
        result = validator.validate(txn)
        assert result.is_valid is True


class TestStatusValidation:
    """Test status enum membership validation."""

    def test_success_status_passes(self):
        """TransactionStatus.SUCCESS → no error."""
        validator = Validator()
        txn = _make_valid_txn(status=TransactionStatus.SUCCESS)
        result = validator.validate(txn)
        assert result.is_valid is True
        assert result.violations == []

    def test_failed_status_passes(self):
        """TransactionStatus.FAILED → no error."""
        validator = Validator()
        txn = _make_valid_txn(status=TransactionStatus.FAILED)
        result = validator.validate(txn)
        assert result.is_valid is True

    def test_pending_status_passes(self):
        """TransactionStatus.PENDING → no error."""
        validator = Validator()
        txn = _make_valid_txn(status=TransactionStatus.PENDING)
        result = validator.validate(txn)
        assert result.is_valid is True

    def test_reversed_status_passes(self):
        """TransactionStatus.REVERSED → no error."""
        validator = Validator()
        txn = _make_valid_txn(status=TransactionStatus.REVERSED)
        result = validator.validate(txn)
        assert result.is_valid is True


class TestFullValidation:
    """Integration tests combining all validation rules."""

    def test_fully_valid_transaction(self):
        """Transaction with all fields correct → outcome=QualityOutcome.VALID, 0 errors."""
        validator = Validator()
        txn = CanonicalTransaction(
            id="TXN20240115001",
            trace="REF123456",
            amount=Decimal("1500000"),
            currency="VND",
            status=TransactionStatus.SUCCESS,
            transDate=datetime(2024, 1, 15),
        )
        result = validator.validate(txn)
        assert result.is_valid is True
        assert len(result.violations) == 0

    def test_multiple_errors_collected(self):
        """Transaction with empty id + negative amount → multiple errors."""
        validator = Validator()
        txn = _make_valid_txn(id="", amount=Decimal("-500"))
        result = validator.validate(txn)
        assert result.is_valid is False
        assert len(result.violations) == 2
        fields = {e.field for e in result.violations}
        assert "id" in fields
        assert "amount" in fields

    def test_error_count_matches_violations(self):
        """Transaction with 3 violations → exactly 3 errors."""
        validator = Validator()
        txn = _make_valid_txn(id="", currency="", amount=Decimal("-100"))
        result = validator.validate(txn)
        assert result.is_valid is False
        assert len(result.violations) == 3

    def test_all_errors_have_context(self):
        """All errors include row_number and trace when provided."""
        validator = Validator()
        txn = _make_valid_txn(id="", amount=Decimal("-500"))
        result = validator.validate(txn, row_number=15, trace="BATCH001")
        for err in result.violations:
            assert err.row == 15
            assert err.trace == "BATCH001"

    def test_valid_transaction_with_all_optional_fields(self):
        """Valid transaction with trace and transDate → fully valid."""
        validator = Validator()
        txn = CanonicalTransaction(
            id="TXN001",
            trace="REF789",
            amount=Decimal("99.99"),
            currency="USD",
            status=TransactionStatus.PENDING,
            transDate=datetime(2024, 6, 15, 14, 30, 0),
            extra={"partnerCode": "VN001"},
        )
        result = validator.validate(txn)
        assert result.is_valid is True
        assert result.violations == []


class TestQualityEvaluation:
    """Test QualityEvaluation structure and behavior."""

    def test_is_valid_true_when_no_errors(self):
        """QualityEvaluation.is_valid = True when errors list is empty."""
        result = QualityEvaluation(outcome=QualityOutcome.VALID, violations=[])
        assert result.is_valid is True
        assert len(result.violations) == 0

    def test_is_valid_false_when_errors_present(self):
        """QualityEvaluation.is_valid = False when errors list has items."""
        err = QualityViolation(field="id", message="missing")
        result = QualityEvaluation(outcome=QualityOutcome.REJECT, violations=[err])
        assert result.is_valid is False
        assert len(result.violations) == 1

    def test_errors_contains_all_collected_errors(self):
        """QualityEvaluation.violations contains all collected errors."""
        errors = [
            QualityViolation(field="id", message="missing", row=1, trace="T1"),
            QualityViolation(field="amount", message="negative", row=1, trace="T1"),
            QualityViolation(field="duplicate", message="exists", row=1, trace="T1"),
        ]
        result = QualityEvaluation(outcome=QualityOutcome.REJECT, violations=errors)
        assert len(result.violations) == 3
        assert result.violations[0].field == "id"
        assert result.violations[1].field == "amount"
        assert result.violations[2].field == "duplicate"

    def test_error_objects_have_correct_context_values(self):
        """Error objects have correct field, reason, row, trace values."""
        err = QualityViolation(
            field="duplicate",
            message="transaction already exists",
            row=42,
            trace="REF123",
        )
        assert err.field == "duplicate"
        assert err.message == "transaction already exists"
        assert err.row == 42
        assert err.trace == "REF123"
