"""Core normalization engine for the reconciliation ingestion platform.

Transforms partner-specific row tuples into canonical field values
using FieldMapping rules, collecting all validation errors rather than
failing fast.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from src.core.enums import TransactionStatus
from src.core.types import CanonicalTransaction, FieldMapping, FieldMappingType
from src.domain.ingestion.quality import (
    QualityOutcome,
    QualityPhase,
    QualityRuleCode,
    QualitySeverity,
    QualityViolation,
    quality_violation,
)
from src.normalizer.timestamps import TimestampParseError, parse_transaction_timestamp


_REQUIRED_CANONICAL_FIELDS = frozenset({"id", "amount", "currency", "status"})


def _normalization_violation(
    *,
    code: QualityRuleCode,
    field: str,
    message: str,
    row: int | None = None,
    expected: Any = None,
    actual: Any = None,
) -> QualityViolation:
    return quality_violation(
        code=code,
        phase=QualityPhase.NORMALIZATION,
        severity=QualitySeverity.ERROR,
        outcome=QualityOutcome.REJECT,
        field=field,
        message=message,
        expected=expected,
        actual=actual,
        row=row,
    )


def _missing_value_code(mapping: FieldMapping) -> QualityRuleCode:
    if mapping.required or mapping.path in _REQUIRED_CANONICAL_FIELDS:
        return QualityRuleCode.MISSING_REQUIRED_FIELD
    return QualityRuleCode.MALFORMED_ROW


@dataclass
class NormalizationResult:
    """Result of a single row normalization.

    Attributes:
        data: Successfully normalized canonical field values keyed by path.
        errors: All conversion/validation errors encountered during normalization.
    """

    data: dict[str, Any] = field(default_factory=dict)
    errors: list[QualityViolation] = field(default_factory=list)


@dataclass
class FieldNormalizationTrace:
    """Debug trace for a single field mapping evaluation."""

    path: str
    mapping_type: str
    column: Any = None
    source_field: Optional[str] = None
    source_value: Any = None
    output_value: Any = None
    error: Optional[QualityViolation] = None


class TransactionNormalizer:
    """Applies FieldMapping rules to raw row tuples.

    Performs type conversions (STRING, DECIMAL, DATE, CONSTANT) and
    collects expected row-quality conversion errors as QualityViolation
    objects; unexpected exceptions propagate to the caller.
    """

    def __init__(self, field_mappings: list[FieldMapping]) -> None:
        """Initialize with a list of field mappings.

        Args:
            field_mappings: List of FieldMapping rules to apply during normalization.

        Raises:
            ValueError: If field_mappings is empty.
        """
        if not field_mappings:
            raise ValueError("field_mappings must not be empty")
        self._field_mappings = field_mappings

    def normalize(
        self,
        row: Any,
        row_number: Optional[int] = None,
    ) -> NormalizationResult:
        """Normalize a single row tuple against configured field mappings.

        Args:
            row: Raw row tuple from ExcelStreamReader (0-indexed).
            row_number: Optional row number for error context.

        Returns:
            NormalizationResult with successfully converted data and any errors.
        """
        result = NormalizationResult(data={}, errors=[])

        for fm in self._field_mappings:
            value: Any = None
            error: Optional[QualityViolation] = None

            # Resolve source value from row (skip for CONSTANT)
            if fm.type == FieldMappingType.CONSTANT:
                value, error = self._convert_constant(fm, row_number)
            else:
                source_value = self._resolve_source(row, fm, row_number)
                if isinstance(source_value, QualityViolation):
                    result.errors.append(source_value)
                    continue
                if source_value is None:
                    # Value is None/empty — produce error
                    error = _normalization_violation(
                        code=_missing_value_code(fm),
                        field=fm.path,
                        message="source field value is None",
                        row=row_number,
                    )
                    result.errors.append(error)
                    continue

                # Apply type-specific conversion
                if fm.type == FieldMappingType.STRING:
                    value, error = self._convert_string(source_value, fm, row_number)
                elif fm.type == FieldMappingType.DECIMAL:
                    if fm.path == "amount":
                        value = source_value
                    else:
                        value, error = self._convert_decimal(
                            source_value, fm, row_number
                        )
                elif fm.type == FieldMappingType.DATE:
                    value, error = self._convert_date(source_value, fm, row_number)
                elif fm.type == FieldMappingType.MAPPING:
                    if fm.mapping is None:
                        error = _normalization_violation(
                            code=QualityRuleCode.MALFORMED_ROW,
                            field=fm.path,
                            message=f"mapping dict not configured for {fm.path}",
                            row=row_number,
                        )
                    else:
                        value, error = self._convert_mapping(source_value, fm, row_number)
                else:
                    # Unknown field mapping type
                    error = _normalization_violation(
                        code=QualityRuleCode.MALFORMED_ROW,
                        field=fm.path,
                        message=f"unknown mapping type '{fm.type}' for path '{fm.path}'",
                        row=row_number,
                    )

            if error is not None:
                result.errors.append(error)
            elif fm.path == "amount" and value is not None:
                amount, amount_error = self._coerce_amount(value, fm, row_number)
                if amount_error is not None:
                    result.errors.append(amount_error)
                else:
                    result.data[fm.path] = amount
            elif value is not None:
                result.data[fm.path] = value

        return result

    def normalize_with_trace(
        self,
        row: Any,
        row_number: Optional[int] = None,
    ) -> tuple[NormalizationResult, list[FieldNormalizationTrace]]:
        """Normalize a row and capture field-level mapping trace data."""
        result = NormalizationResult(data={}, errors=[])
        traces: list[FieldNormalizationTrace] = []

        for fm in self._field_mappings:
            value: Any = None
            error: Optional[QualityViolation] = None
            source_value: Any = None

            if fm.type == FieldMappingType.CONSTANT:
                source_value = fm.constant
                value, error = self._convert_constant(fm, row_number)
            else:
                source_value = self._resolve_source(row, fm, row_number)
                if isinstance(source_value, QualityViolation):
                    error = source_value
                    source_value = None
                elif source_value is None:
                    error = _normalization_violation(
                        code=_missing_value_code(fm),
                        field=fm.path,
                        message="source field value is None",
                        row=row_number,
                    )
                elif fm.type == FieldMappingType.STRING:
                    value, error = self._convert_string(source_value, fm, row_number)
                elif fm.type == FieldMappingType.DECIMAL:
                    if fm.path == "amount":
                        value = source_value
                    else:
                        value, error = self._convert_decimal(
                            source_value, fm, row_number
                        )
                elif fm.type == FieldMappingType.DATE:
                    value, error = self._convert_date(source_value, fm, row_number)
                elif fm.type == FieldMappingType.MAPPING:
                    if fm.mapping is None:
                        error = _normalization_violation(
                            code=QualityRuleCode.MALFORMED_ROW,
                            field=fm.path,
                            message=f"mapping dict not configured for {fm.path}",
                            row=row_number,
                        )
                    else:
                        value, error = self._convert_mapping(source_value, fm, row_number)
                else:
                    error = _normalization_violation(
                        code=QualityRuleCode.MALFORMED_ROW,
                        field=fm.path,
                        message=f"unknown mapping type '{fm.type}' for path '{fm.path}'",
                        row=row_number,
                    )

            if error is None and fm.path == "amount" and value is not None:
                value, error = self._coerce_amount(value, fm, row_number)

            traces.append(
                FieldNormalizationTrace(
                    path=fm.path,
                    mapping_type=str(fm.type),
                    column=fm.column,
                    source_field=fm.sourceField,
                    source_value=source_value,
                    output_value=value,
                    error=error,
                )
            )
            if error is not None:
                result.errors.append(error)
            elif value is not None:
                result.data[fm.path] = value

        return result, traces

    def _resolve_source(
        self,
        row: Any,
        fm: FieldMapping,
        row_number: int | None = None,
    ) -> Any | QualityViolation | None:
        """Resolve the source value from the row using column number/letter or sourceField.

        Returns:
            The resolved value, a QualityViolation if resolution fails, or None
            if the value itself is None/empty (caller should produce error).
        """
        if fm.column is not None:
            if isinstance(row, dict):
                if fm.column in row:
                    return row[fm.column]
                # If column is an int but row has string keys (e.g. "A")
                if isinstance(fm.column, int):
                    from openpyxl.utils import get_column_letter

                    col_letter = get_column_letter(fm.column)
                    if col_letter in row:
                        return row[col_letter]
                # If column is a string but row has int keys
                if isinstance(fm.column, str) and fm.column.isdigit():
                    col_int = int(fm.column)
                    if col_int in row:
                        return row[col_int]
                return _normalization_violation(
                    code=QualityRuleCode.MALFORMED_ROW,
                    field=fm.path,
                    message=f"column {fm.column} not found in row keys: {list(row.keys())}",
                    row=row_number,
                )

            elif isinstance(row, (tuple, list)):
                col_int = None
                if isinstance(fm.column, int):
                    col_int = fm.column
                elif isinstance(fm.column, str):
                    if fm.column.isdigit():
                        col_int = int(fm.column)
                    else:
                        try:
                            from openpyxl.utils import column_index_from_string

                            col_int = column_index_from_string(fm.column)
                        except ValueError:
                            return _normalization_violation(
                                code=QualityRuleCode.MALFORMED_ROW,
                                field=fm.path,
                                message=f"invalid column letter '{fm.column}'",
                                row=row_number,
                            )

                if col_int is not None:
                    idx = col_int - 1
                    if idx < 0 or idx >= len(row):
                        return _normalization_violation(
                            code=QualityRuleCode.MALFORMED_ROW,
                            field=fm.path,
                            message=f"column {fm.column} (index {idx}) out of range (row has {len(row)} columns)",
                            row=row_number,
                        )
                    return row[idx]

        if fm.sourceField is not None:
            if isinstance(row, dict):
                if fm.sourceField in row:
                    return row[fm.sourceField]
                return _normalization_violation(
                    code=QualityRuleCode.MALFORMED_ROW,
                    field=fm.path,
                    message=f"sourceField '{fm.sourceField}' not found in row keys: {list(row.keys())}",
                    row=row_number,
                )
            return _normalization_violation(
                code=QualityRuleCode.MALFORMED_ROW,
                field=fm.path,
                message="sourceField lookup requires dict — use column number instead",
                row=row_number,
            )

        # No column configured for non-CONSTANT mapping
        return _normalization_violation(
            code=QualityRuleCode.MALFORMED_ROW,
            field=fm.path,
            message="no column configured",
            row=row_number,
        )

    @staticmethod
    def _convert_string(
        value: Any,
        fm: FieldMapping,
        row_number: Optional[int],
    ) -> tuple[str | None, QualityViolation | None]:
        """Convert value to string.

        None or empty string values produce a QualityViolation.
        """
        if value is None:
            return None, _normalization_violation(
                code=_missing_value_code(fm),
                field=fm.path,
                message="value is None",
                row=row_number,
            )

        str_value = str(value)
        if str_value == "":
            return None, _normalization_violation(
                code=_missing_value_code(fm),
                field=fm.path,
                message="value is empty string",
                row=row_number,
            )

        return str_value, None

    @staticmethod
    def _convert_decimal(
        value: Any,
        fm: FieldMapping,
        row_number: Optional[int],
    ) -> tuple[Decimal | None, QualityViolation | None]:
        """Convert value to Decimal.

        Float input is explicitly rejected. Invalid strings produce
        QualityViolation with a stable rule code and failure description.
        """
        return TransactionNormalizer._coerce_amount(value, fm, row_number)

    @staticmethod
    def _coerce_amount(
        value: Any,
        fm: FieldMapping,
        row_number: Optional[int],
    ) -> tuple[Decimal | None, QualityViolation | None]:
        """Coerce a transformed canonical amount without exposing its raw value."""
        if value is None:
            return None, _normalization_violation(
                code=_missing_value_code(fm),
                field=fm.path,
                message="value is None",
                row=row_number,
            )

        if isinstance(value, float):
            return None, _normalization_violation(
                code=QualityRuleCode.INVALID_AMOUNT,
                field=fm.path,
                message="float not allowed for monetary values",
                row=row_number,
            )

        try:
            decimal_value = Decimal(str(value))
        except InvalidOperation:
            return None, _normalization_violation(
                code=QualityRuleCode.INVALID_AMOUNT,
                field=fm.path,
                message="invalid decimal value for monetary amount",
                row=row_number,
            )

        error = TransactionNormalizer._normalized_amount_error(
            decimal_value, row_number, field=fm.path
        )
        if error is not None:
            return None, error
        return decimal_value, None

    @staticmethod
    def _normalized_amount_error(
        value: Any,
        row_number: Optional[int],
        *,
        field: str = "amount",
    ) -> QualityViolation | None:
        """Validate the Decimal-only boundary used by canonical builders."""
        if not isinstance(value, Decimal):
            return _normalization_violation(
                code=QualityRuleCode.INVALID_AMOUNT,
                field=field,
                message="amount must be a Decimal monetary value",
                row=row_number,
            )
        if not value.is_finite():
            return _normalization_violation(
                code=QualityRuleCode.INVALID_AMOUNT,
                field=field,
                message="non-finite decimal monetary value",
                row=row_number,
            )
        return None

    def _convert_date(
        self,
        value: Any,
        fm: FieldMapping,
        row_number: Optional[int],
    ) -> tuple[datetime | None, QualityViolation | None]:
        """Convert a source value to a canonical transaction timestamp."""
        if value is None:
            return None, _normalization_violation(
                code=_missing_value_code(fm),
                field=fm.path,
                message="value is None",
                row=row_number,
            )

        try:
            return parse_transaction_timestamp(value), None
        except TimestampParseError:
            return None, _normalization_violation(
                code=QualityRuleCode.INVALID_TIMESTAMP,
                field=fm.path,
                message="Timestamp is not a supported date/time value.",
                expected=(
                    "ISO-8601 datetime with Z/UTC offset or an approved legacy date format"
                ),
                actual={"type": type(value).__name__},
                row=row_number,
            )

    @staticmethod
    def _convert_mapping(
        value: Any,
        fm: FieldMapping,
        row_number: Optional[int] = None,
    ) -> tuple[str | None, QualityViolation | None]:
        """Convert a row value using a configured mapping dictionary.

        Looks up the string representation of *value* in ``fm.mapping``.
        If the value is not found, falls back to the ``"others"`` key if
        present. Missing ``"others"`` produces an explicit QualityViolation
        rather than silently defaulting.

        Returns the mapped string value (not a TransactionStatus enum —
        the caller converts to enum in build_canonical).
        """
        if value is None or value == "":
            return None, _normalization_violation(
                code=_missing_value_code(fm),
                field=fm.path,
                message=f"cannot map empty/null value for path '{fm.path}'",
                row=row_number,
            )

        str_value = str(value)

        if str_value in fm.mapping:
            return fm.mapping[str_value], None

        if "others" in fm.mapping:
            return fm.mapping["others"], None

        return None, _normalization_violation(
            code=(
                QualityRuleCode.INVALID_STATUS
                if fm.path == "status"
                else QualityRuleCode.MALFORMED_ROW
            ),
            field=fm.path,
            message=f"unmapped value '{str_value}' for path '{fm.path}' — no 'others' fallback configured",
            row=row_number,
        )

    @staticmethod
    def _convert_constant(
        fm: FieldMapping,
        row_number: Optional[int],
    ) -> tuple[str | None, QualityViolation | None]:
        """Return the configured constant value.

        None or empty constant produces a QualityViolation.
        """
        if fm.constant is None or fm.constant == "":
            return None, _normalization_violation(
                code=_missing_value_code(fm),
                field=fm.path,
                message="constant value is not configured",
                row=row_number,
            )

        return fm.constant, None

    @staticmethod
    def _extract_extra(data: dict[str, Any]) -> dict[str, Any]:
        """Extract extra fields from normalized data dict.

        Keys not in the canonical schema are collected into the ``extra``
        dict. Dot-separated paths like ``"extra.service"`` become
        ``extra["service"]``.
        """
        canonical_keys = {"id", "trace", "amount", "currency", "status", "transDate"}
        extra: dict[str, Any] = {}
        for k, v in data.items():
            if k in canonical_keys:
                continue
            if "." in k:
                parts = k.split(".", 1)
                if len(parts) == 2:
                    outer, inner = parts
                    if outer == "extra":
                        extra[inner] = v
                    else:
                        if outer not in extra:
                            extra[outer] = {}
                        extra[outer][inner] = v
            else:
                extra[k] = v
        return extra

    @staticmethod
    def build_fast_dict(
        data: dict[str, Any],
        errors: list[QualityViolation],
        row_number: Optional[int] = None,
    ) -> tuple[dict[str, Any] | None, list[QualityViolation]]:
        """Build a lightweight dict from normalized data, skipping Pydantic.

        Validates required fields are present.  Returns a plain dict with
        keys ``id``, ``trace``, ``status``, ``amount``, ``currency``,
        ``transDate``, and ``extra`` — suitable for direct use in the
        fast-mode ingestion pipeline without Pydantic overhead.

        Args:
            data: Normalized canonical field values keyed by path.
            errors: Existing error list (not cleared; new errors appended).
            row_number: Optional row number for error context.

        Returns:
            Tuple of (dict or None, updated error list).
        """
        required_fields = ("id", "amount", "currency", "status")
        new_errors: list[QualityViolation] = []

        for field_name in required_fields:
            if field_name not in data:
                new_errors.append(
                    _normalization_violation(
                        code=QualityRuleCode.MISSING_REQUIRED_FIELD,
                        field=field_name,
                        message=(f"required field '{field_name}' not found in normalized data"),
                        row=row_number,
                    )
                )

        if new_errors:
            return None, errors + new_errors

        # Validate status string
        try:
            TransactionStatus(data["status"])
        except (ValueError, TypeError):
            new_errors.append(
                _normalization_violation(
                    code=QualityRuleCode.INVALID_STATUS,
                    field="status",
                    message=(
                        f"invalid status value '{data['status']}' — must be one of "
                        "SUCCESS, FAILED, PENDING, REVERSED"
                    ),
                    row=row_number,
                )
            )
            return None, errors + new_errors

        amount_error = TransactionNormalizer._normalized_amount_error(
            data["amount"], row_number
        )
        if amount_error is not None:
            return None, errors + [amount_error]

        extra = TransactionNormalizer._extract_extra(data)

        txn = {
            "id": str(data["id"]),
            "trace": str(data["trace"]) if "trace" in data else None,
            "status": data["status"],
            "amount": data["amount"],
            "currency": str(data["currency"]),
            "transDate": data.get("transDate"),
            "extra": extra,
        }

        return txn, errors

    @staticmethod
    def build_canonical(
        data: dict[str, Any],
        errors: list[QualityViolation],
        row_number: Optional[int] = None,
    ) -> tuple[CanonicalTransaction | None, list[QualityViolation]]:
        """Build a CanonicalTransaction from normalized data.

        Validates that all required fields (id, amount, currency, status)
        are present and valid. Missing fields produce QualityViolation
        objects appended to the *errors* list.  Extra fields not in the
        CanonicalTransaction schema are collected into the ``extra`` dict.

        Args:
            data: Normalized canonical field values keyed by path.
            errors: Existing error list (not cleared; new errors appended).
            row_number: Optional row number for error context.

        Returns:
            Tuple of (CanonicalTransaction or None, updated error list).
        """
        required_fields = ("id", "amount", "currency", "status")
        new_errors: list[QualityViolation] = []

        for field_name in required_fields:
            if field_name not in data:
                new_errors.append(
                    _normalization_violation(
                        code=QualityRuleCode.MISSING_REQUIRED_FIELD,
                        field=field_name,
                        message=(f"required field '{field_name}' not found in normalized data"),
                        row=row_number,
                    )
                )

        if new_errors:
            return None, errors + new_errors

        try:
            status_enum = TransactionStatus(data["status"])
        except (ValueError, TypeError):
            new_errors.append(
                _normalization_violation(
                    code=QualityRuleCode.INVALID_STATUS,
                    field="status",
                    message=(
                        f"invalid status value '{data['status']}' — must be one of "
                        "SUCCESS, FAILED, PENDING, REVERSED"
                    ),
                    row=row_number,
                )
            )
            return None, errors + new_errors

        amount_error = TransactionNormalizer._normalized_amount_error(
            data["amount"], row_number
        )
        if amount_error is not None:
            return None, errors + [amount_error]

        extra = TransactionNormalizer._extract_extra(data)

        txn = CanonicalTransaction(
            id=str(data["id"]),
            trace=str(data["trace"]) if "trace" in data else None,
            amount=data["amount"],
            currency=str(data["currency"]),
            status=status_enum,
            transDate=data.get("transDate"),
            extra=extra,
        )

        return txn, errors
