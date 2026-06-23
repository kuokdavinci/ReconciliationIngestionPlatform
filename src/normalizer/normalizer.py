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
from src.core.types import FieldMapping, FieldMappingType, ValidationError, CanonicalTransaction


@dataclass
class NormalizationResult:
    """Result of a single row normalization.

    Attributes:
        data: Successfully normalized canonical field values keyed by path.
        errors: All conversion/validation errors encountered during normalization.
    """

    data: dict[str, Any] = field(default_factory=dict)
    errors: list[ValidationError] = field(default_factory=list)


@dataclass
class FieldNormalizationTrace:
    """Debug trace for a single field mapping evaluation."""

    path: str
    mapping_type: str
    column: Any = None
    source_field: Optional[str] = None
    source_value: Any = None
    output_value: Any = None
    error: Optional[ValidationError] = None


class TransactionNormalizer:
    """Applies FieldMapping rules to raw row tuples.

    Performs type conversions (STRING, DECIMAL, DATE, CONSTANT) and
    collects validation errors. Never raises exceptions — all errors
    are collected as ValidationError objects.
    """

    _DATE_FORMATS = (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
    )

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
            error: Optional[ValidationError] = None

            # Resolve source value from row (skip for CONSTANT)
            if fm.type == FieldMappingType.CONSTANT:
                value, error = self._convert_constant(fm, row_number)
            else:
                source_value = self._resolve_source(row, fm)
                if isinstance(source_value, ValidationError):
                    result.errors.append(source_value)
                    continue
                if source_value is None:
                    # Value is None/empty — produce error
                    error = ValidationError(
                        field=fm.path,
                        reason="source field value is None",
                        row=row_number,
                    )
                    result.errors.append(error)
                    continue

                # Apply type-specific conversion
                if fm.type == FieldMappingType.STRING:
                    value, error = self._convert_string(source_value, fm, row_number)
                elif fm.type == FieldMappingType.DECIMAL:
                    value, error = self._convert_decimal(source_value, fm, row_number)
                elif fm.type == FieldMappingType.DATE:
                    value, error = self._convert_date(source_value, fm, row_number)
                elif fm.type == FieldMappingType.MAPPING:
                    if fm.mapping is None:
                        error = ValidationError(
                            field=fm.path,
                            reason=f"mapping dict not configured for {fm.path}",
                            row=row_number,
                        )
                    else:
                        value, error = self._convert_mapping(source_value, fm, row_number)
                else:
                    # Unknown field mapping type
                    error = ValidationError(
                        field=fm.path,
                        reason=f"unknown mapping type '{fm.type}' for path '{fm.path}'",
                        row=row_number,
                    )

            if error is not None:
                result.errors.append(error)
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
            error: Optional[ValidationError] = None
            source_value: Any = None

            if fm.type == FieldMappingType.CONSTANT:
                source_value = fm.constant
                value, error = self._convert_constant(fm, row_number)
            else:
                source_value = self._resolve_source(row, fm)
                if isinstance(source_value, ValidationError):
                    error = source_value
                    source_value = None
                elif source_value is None:
                    error = ValidationError(
                        field=fm.path,
                        reason="source field value is None",
                        row=row_number,
                    )
                elif fm.type == FieldMappingType.STRING:
                    value, error = self._convert_string(source_value, fm, row_number)
                elif fm.type == FieldMappingType.DECIMAL:
                    value, error = self._convert_decimal(source_value, fm, row_number)
                elif fm.type == FieldMappingType.DATE:
                    value, error = self._convert_date(source_value, fm, row_number)
                elif fm.type == FieldMappingType.MAPPING:
                    if fm.mapping is None:
                        error = ValidationError(
                            field=fm.path,
                            reason=f"mapping dict not configured for {fm.path}",
                            row=row_number,
                        )
                    else:
                        value, error = self._convert_mapping(source_value, fm, row_number)
                else:
                    error = ValidationError(
                        field=fm.path,
                        reason=f"unknown mapping type '{fm.type}' for path '{fm.path}'",
                        row=row_number,
                    )

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
    ) -> Any | ValidationError | None:
        """Resolve the source value from the row using column number/letter or sourceField.

        Returns:
            The resolved value, a ValidationError if resolution fails, or None
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
                return ValidationError(
                    field=fm.path,
                    reason=f"column {fm.column} not found in row keys: {list(row.keys())}",
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
                            return ValidationError(
                                field=fm.path,
                                reason=f"invalid column letter '{fm.column}'",
                            )
                
                if col_int is not None:
                    idx = col_int - 1
                    if idx < 0 or idx >= len(row):
                        return ValidationError(
                            field=fm.path,
                            reason=f"column {fm.column} (index {idx}) out of range (row has {len(row)} columns)",
                        )
                    return row[idx]

        if fm.sourceField is not None:
            if isinstance(row, dict):
                if fm.sourceField in row:
                    return row[fm.sourceField]
                return ValidationError(
                    field=fm.path,
                    reason=f"sourceField '{fm.sourceField}' not found in row keys: {list(row.keys())}",
                )
            return ValidationError(
                field=fm.path,
                reason="sourceField lookup requires dict — use column number instead",
            )

        # No column configured for non-CONSTANT mapping
        return ValidationError(
            field=fm.path,
            reason="no column configured",
        )

    @staticmethod
    def _convert_string(
        value: Any,
        fm: FieldMapping,
        row_number: Optional[int],
    ) -> tuple[str | None, ValidationError | None]:
        """Convert value to string.

        None or empty string values produce a ValidationError.
        """
        if value is None:
            return None, ValidationError(
                field=fm.path,
                reason="value is None",
                row=row_number,
            )

        str_value = str(value)
        if str_value == "":
            return None, ValidationError(
                field=fm.path,
                reason="value is empty string",
                row=row_number,
            )

        return str_value, None

    @staticmethod
    def _convert_decimal(
        value: Any,
        fm: FieldMapping,
        row_number: Optional[int],
    ) -> tuple[Decimal | None, ValidationError | None]:
        """Convert value to Decimal.

        Float input is explicitly rejected. Invalid strings produce
        ValidationError with description of the failure.
        """
        if value is None:
            return None, ValidationError(
                field=fm.path,
                reason="value is None",
                row=row_number,
            )

        if isinstance(value, float):
            return None, ValidationError(
                field=fm.path,
                reason="float not allowed for monetary values",
                row=row_number,
            )

        try:
            return Decimal(str(value)), None
        except InvalidOperation:
            return None, ValidationError(
                field=fm.path,
                reason=f"invalid decimal value: {value!r}",
                row=row_number,
            )

    def _convert_date(
        self,
        value: Any,
        fm: FieldMapping,
        row_number: Optional[int],
    ) -> tuple[datetime | None, ValidationError | None]:
        """Convert value to datetime.

        Already datetime objects are returned as-is. String values are
        parsed against a whitelist of 4 date formats. Unmatched formats
        produce ValidationError.
        """
        if value is None:
            return None, ValidationError(
                field=fm.path,
                reason="value is None",
                row=row_number,
            )

        if isinstance(value, datetime):
            return value, None

        if not isinstance(value, str):
            return None, ValidationError(
                field=fm.path,
                reason=f"expected string or datetime, got {type(value).__name__}",
                row=row_number,
            )

        for fmt in self._DATE_FORMATS:
            try:
                return datetime.strptime(value, fmt), None
            except ValueError:
                continue

        return None, ValidationError(
            field=fm.path,
            reason=f"invalid date value: {value!r} (tried formats: {', '.join(self._DATE_FORMATS)})",
            row=row_number,
        )

    @staticmethod
    def _convert_mapping(
        value: Any,
        fm: FieldMapping,
        row_number: Optional[int] = None,
    ) -> tuple[str | None, ValidationError | None]:
        """Convert a row value using a configured mapping dictionary.

        Looks up the string representation of *value* in ``fm.mapping``.
        If the value is not found, falls back to the ``"others"`` key if
        present.  Missing ``"others"`` produces an explicit ValidationError
        rather than silently defaulting.

        Returns the mapped string value (not a TransactionStatus enum —
        the caller converts to enum in build_canonical).
        """
        if value is None or value == "":
            return None, ValidationError(
                field=fm.path,
                reason=f"cannot map empty/null value for path '{fm.path}'",
                row=row_number,
            )

        str_value = str(value)

        if str_value in fm.mapping:
            return fm.mapping[str_value], None

        if "others" in fm.mapping:
            return fm.mapping["others"], None

        return None, ValidationError(
            field=fm.path,
            reason=f"unmapped value '{str_value}' for path '{fm.path}' — no 'others' fallback configured",
            row=row_number,
        )

    @staticmethod
    def _convert_constant(
        fm: FieldMapping,
        row_number: Optional[int],
    ) -> tuple[str | None, ValidationError | None]:
        """Return the configured constant value.

        None or empty constant produces ValidationError.
        """
        if fm.constant is None or fm.constant == "":
            return None, ValidationError(
                field=fm.path,
                reason="constant value is not configured",
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
        errors: list[ValidationError],
        row_number: Optional[int] = None,
    ) -> tuple[dict[str, Any] | None, list[ValidationError]]:
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
        new_errors: list[ValidationError] = []

        for field_name in required_fields:
            if field_name not in data:
                new_errors.append(ValidationError(
                    field=field_name,
                    reason=f"required field '{field_name}' not found in normalized data",
                    row=row_number,
                ))

        if new_errors:
            return None, errors + new_errors

        # Validate status string
        try:
            TransactionStatus(data["status"])
        except (ValueError, TypeError):
            new_errors.append(ValidationError(
                field="status",
                reason=f"invalid status value '{data['status']}' — must be one of SUCCESS, FAILED, PENDING, REVERSED",
                row=row_number,
            ))
            return None, errors + new_errors

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
        errors: list[ValidationError],
        row_number: Optional[int] = None,
    ) -> tuple[CanonicalTransaction | None, list[ValidationError]]:
        """Build a CanonicalTransaction from normalized data.

        Validates that all required fields (id, amount, currency, status)
        are present and valid.  Missing fields produce ValidationError
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
        new_errors: list[ValidationError] = []

        for field_name in required_fields:
            if field_name not in data:
                new_errors.append(ValidationError(
                    field=field_name,
                    reason=f"required field '{field_name}' not found in normalized data",
                    row=row_number,
                ))

        if new_errors:
            return None, errors + new_errors

        try:
            status_enum = TransactionStatus(data["status"])
        except (ValueError, TypeError):
            new_errors.append(ValidationError(
                field="status",
                reason=f"invalid status value '{data['status']}' — must be one of SUCCESS, FAILED, PENDING, REVERSED",
                row=row_number,
            ))
            return None, errors + new_errors

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
