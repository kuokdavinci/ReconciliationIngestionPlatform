"""MappingConfig validation logic for field mapping integrity checks.

Validates that loaded configs are well-formed before use by ConfigLoader.
Detects missing required fields, invalid mapping types, and structural issues.
"""

import re
from typing import Optional

from pydantic import BaseModel

from src.domain.mapping.models import MappingConfig


class ConfigValidationError(BaseModel):
    """A validation error for a specific field in a MappingConfig."""

    field: str
    reason: str
    config_version: Optional[str] = None


class ConfigValidator:
    """Validates MappingConfig field mapping integrity.

    Checks for:
    - Empty field_mappings array
    - Duplicate paths in field_mappings
    - CONSTANT type without constant value
    - MAPPING type without mapping dict
    - Required fields without column or constant (unresolvable)
    - Invalid column format (must be uppercase letters only)
    """

    COLUMN_PATTERN = re.compile(r"^[A-Z]+$")

    @staticmethod
    def validate(config: MappingConfig) -> list[ConfigValidationError]:
        """Validate a MappingConfig and return list of errors (empty = valid).

        Args:
            config: The MappingConfig to validate

        Returns:
            List of ConfigValidationError objects. Empty list means config is valid.
        """
        errors: list[ConfigValidationError] = []
        version = config.config_version

        # Check empty field_mappings
        if not config.field_mappings:
            errors.append(ConfigValidationError(
                field="_global",
                reason="field_mappings is empty — config has no field mappings defined",
                config_version=version,
            ))
            return errors

        # Check for duplicate paths
        seen_paths: dict[str, int] = {}
        for fm in config.field_mappings:
            if fm.path in seen_paths:
                errors.append(ConfigValidationError(
                    field=fm.path,
                    reason=f"duplicate path '{fm.path}' — same canonical path mapped multiple times",
                    config_version=version,
                ))
            else:
                seen_paths[fm.path] = 1

        # Validate each field mapping
        for fm in config.field_mappings:
            # CONSTANT type must have non-empty constant value
            if fm.type.value == "CONSTANT" and not fm.constant:
                errors.append(ConfigValidationError(
                    field=fm.path,
                    reason=f"CONSTANT type requires a non-empty constant value for path '{fm.path}'",
                    config_version=version,
                ))

            # MAPPING type must have non-empty mapping dict
            if fm.type.value == "MAPPING" and not fm.mapping:
                errors.append(ConfigValidationError(
                    field=fm.path,
                    reason=f"MAPPING type requires a non-empty mapping dict for path '{fm.path}'",
                    config_version=version,
                ))

            # Required field must have a resolvable source.
            # JSON/API mappings use sourceField instead of spreadsheet column.
            if fm.required and not fm.column and not fm.sourceField and not fm.constant:
                errors.append(ConfigValidationError(
                    field=fm.path,
                    reason=f"required field '{fm.path}' has no column, sourceField or constant — cannot be resolved",
                    config_version=version,
                ))

            # Column format validation (if column is set)
            # column is now an int (1-based), skip format validation
            if fm.column is not None and isinstance(fm.column, str):
                col_upper = fm.column.upper()
                if not ConfigValidator.COLUMN_PATTERN.match(col_upper):
                    errors.append(ConfigValidationError(
                        field=fm.path,
                        reason=f"invalid column format '{fm.column}' — must be uppercase letters only (A-Z, AA-ZZ, etc.)",
                        config_version=version,
                    ))

        return errors

    @staticmethod
    def validate_required_coverage(
        config: MappingConfig,
        required_paths: set[str],
    ) -> list[ConfigValidationError]:
        """Check that all required paths have a corresponding field mapping.

        Args:
            config: The MappingConfig to check
            required_paths: Set of paths that must be mapped

        Returns:
            List of ConfigValidationError for each missing required path.
        """
        errors: list[ConfigValidationError] = []
        version = config.config_version
        mapped_paths = {fm.path for fm in config.field_mappings}

        for path in required_paths:
            if path not in mapped_paths:
                errors.append(ConfigValidationError(
                    field=path,
                    reason=f"required path '{path}' has no field mapping",
                    config_version=version,
                ))

        return errors
