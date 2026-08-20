"""Deterministic file and row quality gates for ingestion."""

from pathlib import Path
from typing import Any, Iterable
from zipfile import BadZipFile

from openpyxl.utils.exceptions import InvalidFileException

from src.config.signature import (
    compute_signature,
    structure_signature_shape,
    structure_signatures_equivalent,
)
from src.config.validator import ConfigValidator
from src.domain.ingestion.quality import (
    QualityEvaluation,
    QualityOutcome,
    QualityPhase,
    QualityRuleCode,
    QualitySeverity,
    QualityViolation,
    quality_violation,
)
from src.core.types import FieldMapping
from src.domain.mapping.models import MappingConfig


REQUIRED_SCHEMA_PATHS = frozenset({"id", "amount", "currency", "status"})


class QualityGateFailure(ValueError):
    """Raised only for a structural/config quality gate failure."""

    def __init__(self, violations: list[QualityViolation]) -> None:
        self.violations = violations
        message = "; ".join(item.message for item in violations) or "Quality gate failed."
        super().__init__(message)


class SourceStructureUnreadableError(Exception):
    """Raised when the source header/shape cannot be inspected safely."""


def _column_index(column: Any) -> int | None:
    if isinstance(column, int):
        return column
    if isinstance(column, str):
        if column.isdigit():
            return int(column)
        try:
            from openpyxl.utils import column_index_from_string

            return column_index_from_string(column.upper())
        except ValueError:
            return None
    return None


class FileQualityGate:
    """Validate config/file structure before opening the row-processing loop."""

    def evaluate(
        self,
        config: MappingConfig,
        *,
        headers: Iterable[Any] | None = None,
        column_count: int | None = None,
        file_path: str | Path | None = None,
    ) -> QualityEvaluation:
        structure_inspected = (
            headers is not None or column_count is not None or file_path is not None
        )
        if file_path is not None and headers is None:
            try:
                signature = compute_signature(file_path, sample_size=0)
            except (OSError, ValueError, BadZipFile, InvalidFileException) as exc:
                raise SourceStructureUnreadableError(str(exc)) from exc
            headers = signature.headers
            column_count = signature.column_count

        normalized_headers = [str(header).strip() for header in headers or []]
        if column_count is None and normalized_headers:
            column_count = len(normalized_headers)

        violations: list[QualityViolation] = []
        violations.extend(ConfigValidator.validate(config))
        mappings = list(config.field_mappings or [])
        mapped_paths = {mapping.path for mapping in mappings}

        for path in sorted(REQUIRED_SCHEMA_PATHS - mapped_paths):
            violations.append(
                self._fatal(
                    code=QualityRuleCode.REQUIRED_SCHEMA_PATH,
                    field=path,
                    message=f"Required schema path '{path}' has no field mapping.",
                    expected="mapped field path",
                    actual=None,
                )
            )

        violations.extend(
            self._validate_mapping_sources(
                mappings,
                normalized_headers,
                column_count,
                structure_inspected=structure_inspected,
            )
        )

        expected_signature = getattr(config, "structure_signature", None)
        actual_signature = {
            "headers": normalized_headers,
            "columnCount": column_count or len(normalized_headers),
        }
        if (
            expected_signature
            and normalized_headers
            and not structure_signatures_equivalent(expected_signature, actual_signature)
        ):
            append_only = self._is_append_only_drift(
                expected_signature,
                actual_signature,
            )
            violation_factory = self._warning if append_only else self._fatal
            violations.append(
                violation_factory(
                    code=QualityRuleCode.SCHEMA_CONFIG_DRIFT,
                    field="_schema",
                    message=(
                        "Source structure has non-breaking columns appended to the "
                        "approved mapping signature."
                        if append_only
                        else "Source structure differs from the approved mapping signature."
                    ),
                    expected=expected_signature,
                    actual=actual_signature,
                )
            )

        has_fatal = any(violation.outcome is QualityOutcome.BATCH_FATAL for violation in violations)
        return QualityEvaluation(
            outcome=(
                QualityOutcome.BATCH_FATAL
                if has_fatal
                else QualityOutcome.WARNING
                if violations
                else QualityOutcome.VALID
            ),
            violations=violations,
            row_context={"phase": QualityPhase.FILE.value},
        )

    def validate(self, config: MappingConfig, **kwargs: Any) -> QualityEvaluation:
        """Alias used by application callers that name gates validators."""

        return self.evaluate(config, **kwargs)

    @staticmethod
    def _fatal(
        *,
        code: QualityRuleCode,
        field: str,
        message: str,
        expected: Any,
        actual: Any,
    ) -> QualityViolation:
        return quality_violation(
            code=code,
            phase=QualityPhase.FILE,
            severity=QualitySeverity.FATAL,
            outcome=QualityOutcome.BATCH_FATAL,
            field=field,
            message=message,
            expected=expected,
            actual=actual,
        )

    @staticmethod
    def _warning(
        *,
        code: QualityRuleCode,
        field: str,
        message: str,
        expected: Any,
        actual: Any,
    ) -> QualityViolation:
        return quality_violation(
            code=code,
            phase=QualityPhase.FILE,
            severity=QualitySeverity.WARNING,
            outcome=QualityOutcome.WARNING,
            field=field,
            message=message,
            expected=expected,
            actual=actual,
        )

    @staticmethod
    def _is_append_only_drift(expected: Any, actual: Any) -> bool:
        expected_shape = structure_signature_shape(expected)
        actual_shape = structure_signature_shape(actual)
        if expected_shape is None or actual_shape is None:
            return False
        expected_headers, expected_count = expected_shape
        actual_headers, actual_count = actual_shape
        return actual_count > expected_count and actual_headers[:expected_count] == expected_headers

    def _validate_mapping_sources(
        self,
        mappings: list[FieldMapping],
        headers: list[str],
        column_count: int | None,
        *,
        structure_inspected: bool,
    ) -> list[QualityViolation]:
        violations: list[QualityViolation] = []
        for mapping in mappings:
            if mapping.type.value == "CONSTANT":
                continue
            required = mapping.required or mapping.path in REQUIRED_SCHEMA_PATHS
            if mapping.column is not None and column_count is not None:
                index = _column_index(mapping.column)
                if index is None or index < 1 or index > column_count:
                    if required:
                        violations.append(
                            self._fatal(
                                code=QualityRuleCode.MISSING_REQUIRED_SOURCE_COLUMN,
                                field=mapping.path,
                                message=(
                                    f"Required source column '{mapping.column}' is not present "
                                    f"in the file ({column_count} columns)."
                                ),
                                expected=f"column <= {column_count}",
                                actual=mapping.column,
                            )
                        )
                elif headers and index <= len(headers) and not headers[index - 1]:
                    if required:
                        violations.append(
                            self._fatal(
                                code=QualityRuleCode.MISSING_REQUIRED_SOURCE_COLUMN,
                                field=mapping.path,
                                message=f"Required source column for '{mapping.path}' has no header.",
                                expected="non-empty header",
                                actual=headers[index - 1],
                            )
                        )
            elif (
                mapping.sourceField is not None
                and structure_inspected
                and mapping.sourceField not in headers
            ):
                if required:
                    violations.append(
                        self._fatal(
                            code=QualityRuleCode.MISSING_REQUIRED_SOURCE_COLUMN,
                            field=mapping.path,
                            message=f"Required source field '{mapping.sourceField}' is not present.",
                            expected=mapping.sourceField,
                            actual=headers,
                        )
                    )
            elif mapping.column is None and mapping.sourceField is None and required:
                violations.append(
                    self._fatal(
                        code=QualityRuleCode.REQUIRED_SCHEMA_PATH,
                        field=mapping.path,
                        message=f"Required mapping '{mapping.path}' has no source reference.",
                        expected="column or sourceField",
                        actual=None,
                    )
                )
        return violations


QualityGate = FileQualityGate


__all__ = [
    "FileQualityGate",
    "QualityGate",
    "QualityGateFailure",
    "REQUIRED_SCHEMA_PATHS",
    "SourceStructureUnreadableError",
]
