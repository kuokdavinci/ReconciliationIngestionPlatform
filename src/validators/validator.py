"""Deterministic canonical transaction quality validation."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from src.core.enums import TransactionStatus
from src.domain.ingestion.quality import (
    QualityEvaluation,
    QualityOutcome,
    QualityPhase,
    QualityRuleCode,
    QualitySeverity,
    QualityViolation,
    quality_violation,
)
from src.core.types import CanonicalTransaction


_VALID_CONTEXT_FREE_EVALUATION = QualityEvaluation(
    outcome=QualityOutcome.VALID,
    violations=[],
)


class Validator:
    """Validate canonical or fast-path transaction payloads without I/O."""

    @staticmethod
    def _value(txn: Any, field: str) -> Any:
        if isinstance(txn, dict):
            return txn.get(field)
        return getattr(txn, field, None)

    def validate(
        self,
        txn: CanonicalTransaction | dict[str, Any],
        row_number: int | None = None,
        trace: str | None = None,
        *,
        include_context: bool = True,
    ) -> QualityEvaluation:
        """Return all deterministic row violations, including in fast mode.

        The row pipeline keeps row context in ``RowOutcome``. It can therefore
        request a shared context-free valid evaluation and avoid constructing a
        Pydantic model for every clean row. Direct callers retain the contextual
        evaluation by default.
        """

        violations: list[QualityViolation] = []
        trace = trace or self._value(txn, "trace")
        self._validate_required_fields(txn, violations, row_number, trace)
        self._validate_decimal(txn, violations, row_number, trace)
        self._validate_date(txn, violations, row_number, trace)
        self._validate_status(txn, violations, row_number, trace)
        if not violations and not include_context:
            return _VALID_CONTEXT_FREE_EVALUATION
        return QualityEvaluation(
            outcome=QualityOutcome.REJECT if violations else QualityOutcome.VALID,
            violations=violations,
            row_context=({"rowNumber": row_number, "trace": trace} if include_context else {}),
        )

    @staticmethod
    def _append(
        violations: list[QualityViolation],
        *,
        code: QualityRuleCode,
        field: str,
        message: str,
        row: int | None,
        trace: str | None,
        expected: Any = None,
        actual: Any = None,
    ) -> None:
        violations.append(
            quality_violation(
                code=code,
                phase=QualityPhase.VALIDATION,
                severity=QualitySeverity.ERROR,
                outcome=QualityOutcome.REJECT,
                field=field,
                message=message,
                expected=expected,
                actual=actual,
                row=row,
                trace=trace,
            )
        )

    def _validate_required_fields(
        self,
        txn: Any,
        violations: list[QualityViolation],
        row_number: int | None,
        trace: str | None,
    ) -> None:
        for field in ("id", "currency"):
            value = self._value(txn, field)
            if value is None or (isinstance(value, str) and value.strip() == ""):
                self._append(
                    violations,
                    code=QualityRuleCode.MISSING_REQUIRED_FIELD,
                    field=field,
                    message=f"Required field '{field}' is empty or missing.",
                    expected="non-empty value",
                    actual=value,
                    row=row_number,
                    trace=trace,
                )
        for field in ("amount", "status"):
            value = self._value(txn, field)
            if value is None or (
                field == "status" and isinstance(value, str) and value.strip() == ""
            ):
                self._append(
                    violations,
                    code=QualityRuleCode.MISSING_REQUIRED_FIELD,
                    field=field,
                    message=f"Required field '{field}' is missing.",
                    expected="value",
                    actual=value,
                    row=row_number,
                    trace=trace,
                )

    def _validate_decimal(
        self,
        txn: Any,
        violations: list[QualityViolation],
        row_number: int | None,
        trace: str | None,
    ) -> None:
        amount = self._value(txn, "amount")
        if amount is None:
            return
        if not isinstance(amount, Decimal):
            self._append(
                violations,
                code=QualityRuleCode.INVALID_AMOUNT,
                field="amount",
                message="Amount must be a Decimal-compatible monetary value.",
                expected="Decimal",
                actual=amount,
                row=row_number,
                trace=trace,
            )
            return
        if not amount.is_finite():
            self._append(
                violations,
                code=QualityRuleCode.INVALID_AMOUNT,
                field="amount",
                message="Amount must be a finite Decimal monetary value.",
                expected="finite Decimal",
                actual=amount,
                row=row_number,
                trace=trace,
            )
            return
        if amount < 0:
            self._append(
                violations,
                code=QualityRuleCode.NEGATIVE_AMOUNT,
                field="amount",
                message=f"Amount must be non-negative, got {amount}.",
                expected=">= 0",
                actual=amount,
                row=row_number,
                trace=trace,
            )

    def _validate_date(
        self,
        txn: Any,
        violations: list[QualityViolation],
        row_number: int | None,
        trace: str | None,
    ) -> None:
        value = self._value(txn, "transDate")
        if value is not None and not isinstance(value, datetime):
            self._append(
                violations,
                code=QualityRuleCode.INVALID_TIMESTAMP,
                field="transDate",
                message="transDate must be a datetime object.",
                expected="datetime",
                actual=value,
                row=row_number,
                trace=trace,
            )

    def _validate_status(
        self,
        txn: Any,
        violations: list[QualityViolation],
        row_number: int | None,
        trace: str | None,
    ) -> None:
        value = self._value(txn, "status")
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return
        try:
            TransactionStatus(value)
        except (ValueError, TypeError):
            self._append(
                violations,
                code=QualityRuleCode.INVALID_STATUS,
                field="status",
                message=(
                    f"Invalid status value '{value}' — must be one of "
                    f"{', '.join(item.value for item in TransactionStatus)}."
                ),
                expected=[item.value for item in TransactionStatus],
                actual=value,
                row=row_number,
                trace=trace,
            )


__all__ = ["Validator"]
