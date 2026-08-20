"""Runtime validation for mapping configuration integrity."""

import re

from src.domain.ingestion.quality import (
    QualityPhase,
    QualityRuleCode,
    QualitySeverity,
    QualityOutcome,
    QualityViolation,
    quality_violation,
)
from src.domain.mapping.models import MappingConfig


class ConfigValidator:
    """Validate mapping structure before a source file enters row processing."""

    COLUMN_PATTERN = re.compile(r"^[A-Z]+$")

    @staticmethod
    def _error(
        field: str,
        message: str,
        version: str | None,
        *,
        code: QualityRuleCode = QualityRuleCode.CONFIG_VALIDATION,
    ) -> QualityViolation:
        violation = quality_violation(
            code=code,
            phase=QualityPhase.CONFIGURATION,
            severity=QualitySeverity.FATAL,
            outcome=QualityOutcome.BATCH_FATAL,
            field=field,
            message=message,
        )
        # Keep configVersion available to persistence/application diagnostics
        # without requiring a separate configuration error model.
        violation.config_version = version
        return violation

    @staticmethod
    def validate(config: MappingConfig) -> list[QualityViolation]:
        errors: list[QualityViolation] = []
        version = config.config_version
        mappings = config.field_mappings or []
        if not mappings:
            return [
                ConfigValidator._error(
                    "_global",
                    "field_mappings is empty — config has no field mappings defined",
                    version,
                )
            ]

        seen_paths: set[str] = set()
        for mapping in mappings:
            if mapping.path in seen_paths:
                errors.append(
                    ConfigValidator._error(
                        mapping.path,
                        f"duplicate path '{mapping.path}' — same canonical path mapped multiple times",
                        version,
                    )
                )
            seen_paths.add(mapping.path)

            if mapping.type.value == "CONSTANT" and not mapping.constant:
                errors.append(
                    ConfigValidator._error(
                        mapping.path,
                        f"CONSTANT type requires a non-empty constant value for path '{mapping.path}'",
                        version,
                    )
                )
            if mapping.type.value == "MAPPING" and not mapping.mapping:
                errors.append(
                    ConfigValidator._error(
                        mapping.path,
                        f"MAPPING type requires a non-empty mapping dict for path '{mapping.path}'",
                        version,
                    )
                )
            if (
                mapping.required
                and not mapping.column
                and not mapping.sourceField
                and not mapping.constant
            ):
                errors.append(
                    ConfigValidator._error(
                        mapping.path,
                        f"required field '{mapping.path}' has no column, sourceField or constant — cannot be resolved",
                        version,
                    )
                )
            if mapping.column is not None and isinstance(mapping.column, str):
                if not ConfigValidator.COLUMN_PATTERN.match(mapping.column.upper()):
                    errors.append(
                        ConfigValidator._error(
                            mapping.path,
                            f"invalid column format '{mapping.column}' — must be uppercase letters only (A-Z, AA-ZZ, etc.)",
                            version,
                        )
                    )
        return errors

    @staticmethod
    def validate_required_coverage(
        config: MappingConfig,
        required_paths: set[str],
    ) -> list[QualityViolation]:
        mapped_paths = {mapping.path for mapping in config.field_mappings or []}
        return [
            ConfigValidator._error(
                path,
                f"required path '{path}' has no field mapping",
                config.config_version,
                code=QualityRuleCode.REQUIRED_SCHEMA_PATH,
            )
            for path in sorted(required_paths - mapped_paths)
        ]


__all__ = ["ConfigValidator"]
