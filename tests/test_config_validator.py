"""Tests for ConfigValidator — field mapping integrity checks."""



from src.core.enums import FileType
from src.core.types import FieldMapping, FieldMappingType
from src.models.mapping_config import MappingConfig


def _make_config(field_mappings: list[FieldMapping], version: str | None = None) -> MappingConfig:
    """Helper to create a MappingConfig with given field mappings."""
    return MappingConfig(
        partner="MOMO",
        workflowType="UPC",
        fileType=FileType.SETTLEMENT,
        sheetName="Sheet1",
        fieldMappings=field_mappings,
        configVersion=version,
    )


class TestConfigValidationError:
    """Tests for ConfigValidationError model."""

    def test_error_has_field_and_reason(self):
        """ConfigValidationError stores field and reason."""
        from src.config.validator import ConfigValidationError

        err = ConfigValidationError(field="amount", reason="duplicate path")

        assert err.field == "amount"
        assert err.reason == "duplicate path"

    def test_error_has_optional_config_version(self):
        """ConfigValidationError stores optional config_version."""
        from src.config.validator import ConfigValidationError

        err = ConfigValidationError(
            field="amount",
            reason="duplicate path",
            config_version="v1.0",
        )

        assert err.config_version == "v1.0"

    def test_error_config_version_defaults_to_none(self):
        """ConfigValidationError.config_version defaults to None."""
        from src.config.validator import ConfigValidationError

        err = ConfigValidationError(field="amount", reason="test")

        assert err.config_version is None


class TestConfigValidatorValidConfig:
    """Tests for valid configuration returning empty errors."""

    def test_valid_config_returns_empty_list(self):
        """validate() returns empty list for well-formed config."""
        from src.config.validator import ConfigValidator

        mappings = [
            FieldMapping(path="amount", column="D", type=FieldMappingType.DECIMAL, required=True),
            FieldMapping(path="currency", constant="VND", type=FieldMappingType.CONSTANT),
            FieldMapping(path="status", column="F", type=FieldMappingType.STRING),
        ]
        config = _make_config(mappings)

        errors = ConfigValidator.validate(config)

        assert errors == []


class TestConfigValidatorDuplicatePaths:
    """Tests for duplicate path detection."""

    def test_duplicate_paths_detected(self):
        """validate() detects when same path is mapped twice."""
        from src.config.validator import ConfigValidator

        mappings = [
            FieldMapping(path="amount", column="D", type=FieldMappingType.DECIMAL),
            FieldMapping(path="amount", column="E", type=FieldMappingType.DECIMAL),
        ]
        config = _make_config(mappings)

        errors = ConfigValidator.validate(config)

        assert len(errors) == 1
        assert errors[0].field == "amount"
        assert "duplicate" in errors[0].reason.lower()


class TestConfigValidatorConstantType:
    """Tests for CONSTANT type validation."""

    def test_constant_without_value(self):
        """validate() detects CONSTANT type without constant value."""
        from src.config.validator import ConfigValidator

        mappings = [
            FieldMapping(path="currency", type=FieldMappingType.CONSTANT, constant=None),
        ]
        config = _make_config(mappings)

        errors = ConfigValidator.validate(config)

        assert len(errors) == 1
        assert errors[0].field == "currency"
        assert "constant" in errors[0].reason.lower()

    def test_constant_with_empty_string_value(self):
        """validate() detects CONSTANT type with empty string value."""
        from src.config.validator import ConfigValidator

        mappings = [
            FieldMapping(path="currency", type=FieldMappingType.CONSTANT, constant=""),
        ]
        config = _make_config(mappings)

        errors = ConfigValidator.validate(config)

        assert len(errors) == 1
        assert errors[0].field == "currency"

    def test_constant_with_value_is_valid(self):
        """validate() accepts CONSTANT type with non-empty value."""
        from src.config.validator import ConfigValidator

        mappings = [
            FieldMapping(path="currency", type=FieldMappingType.CONSTANT, constant="VND"),
        ]
        config = _make_config(mappings)

        errors = ConfigValidator.validate(config)

        assert errors == []


class TestConfigValidatorMappingType:
    """Tests for MAPPING type validation."""

    def test_mapping_without_dict(self):
        """validate() detects MAPPING type without mapping dict."""
        from src.config.validator import ConfigValidator

        mappings = [
            FieldMapping(path="status", type=FieldMappingType.MAPPING, mapping=None),
        ]
        config = _make_config(mappings)

        errors = ConfigValidator.validate(config)

        assert len(errors) == 1
        assert errors[0].field == "status"
        assert "mapping" in errors[0].reason.lower()

    def test_mapping_with_empty_dict(self):
        """validate() detects MAPPING type with empty mapping dict."""
        from src.config.validator import ConfigValidator

        mappings = [
            FieldMapping(path="status", type=FieldMappingType.MAPPING, mapping={}),
        ]
        config = _make_config(mappings)

        errors = ConfigValidator.validate(config)

        assert len(errors) == 1
        assert errors[0].field == "status"

    def test_mapping_with_dict_is_valid(self):
        """validate() accepts MAPPING type with non-empty mapping dict."""
        from src.config.validator import ConfigValidator

        mappings = [
            FieldMapping(
                path="status",
                type=FieldMappingType.MAPPING,
                mapping={"1": "SUCCESS", "0": "FAILED"},
            ),
        ]
        config = _make_config(mappings)

        errors = ConfigValidator.validate(config)

        assert errors == []


class TestConfigValidatorRequiredFields:
    """Tests for required field validation."""

    def test_required_without_column_or_constant(self):
        """validate() detects required=True with no column or constant."""
        from src.config.validator import ConfigValidator

        mappings = [
            FieldMapping(path="amount", type=FieldMappingType.DECIMAL, required=True),
        ]
        config = _make_config(mappings)

        errors = ConfigValidator.validate(config)

        assert len(errors) == 1
        assert errors[0].field == "amount"
        assert "required" in errors[0].reason.lower()

    def test_required_with_column_is_valid(self):
        """validate() accepts required=True with column set."""
        from src.config.validator import ConfigValidator

        mappings = [
            FieldMapping(path="amount", column="D", type=FieldMappingType.DECIMAL, required=True),
        ]
        config = _make_config(mappings)

        errors = ConfigValidator.validate(config)

        assert errors == []

    def test_required_with_constant_is_valid(self):
        """validate() accepts required=True with constant set."""
        from src.config.validator import ConfigValidator

        mappings = [
            FieldMapping(path="currency", type=FieldMappingType.CONSTANT, required=True, constant="VND"),
        ]
        config = _make_config(mappings)

        errors = ConfigValidator.validate(config)

        assert errors == []


class TestConfigValidatorColumnFormat:
    """Tests for column format validation."""

    def test_lowercase_column_is_accepted_case_insensitive(self):
        """validate() accepts lowercase column (case-insensitive per plan)."""
        from src.config.validator import ConfigValidator

        mappings = [
            FieldMapping(path="amount", column="d", type=FieldMappingType.DECIMAL),
        ]
        config = _make_config(mappings)

        errors = ConfigValidator.validate(config)

        # Plan says "case-insensitive, store uppercase" — lowercase is accepted
        assert errors == []

    def test_invalid_column_format_with_numbers(self):
        """validate() detects column format with numbers."""
        from src.config.validator import ConfigValidator

        mappings = [
            FieldMapping(path="amount", column="D1", type=FieldMappingType.DECIMAL),
        ]
        config = _make_config(mappings)

        errors = ConfigValidator.validate(config)

        assert len(errors) == 1
        assert errors[0].field == "amount"

    def test_valid_column_format_single_letter(self):
        """validate() accepts single uppercase letter column."""
        from src.config.validator import ConfigValidator

        mappings = [
            FieldMapping(path="amount", column="D", type=FieldMappingType.DECIMAL),
        ]
        config = _make_config(mappings)

        errors = ConfigValidator.validate(config)

        assert errors == []

    def test_valid_column_format_double_letter(self):
        """validate() accepts double uppercase letter column (AA-ZZ)."""
        from src.config.validator import ConfigValidator

        mappings = [
            FieldMapping(path="amount", column="AA", type=FieldMappingType.DECIMAL),
        ]
        config = _make_config(mappings)

        errors = ConfigValidator.validate(config)

        assert errors == []


class TestConfigValidatorEmptyMappings:
    """Tests for empty field_mappings detection."""

    def test_empty_field_mappings_detected(self):
        """validate() detects empty field_mappings array."""
        from src.config.validator import ConfigValidator

        config = _make_config([])

        errors = ConfigValidator.validate(config)

        assert len(errors) == 1
        assert "empty" in errors[0].reason.lower()


class TestConfigValidatorRequiredCoverage:
    """Tests for validate_required_coverage()."""

    def test_required_coverage_passes(self):
        """validate_required_coverage() returns empty when all paths covered."""
        from src.config.validator import ConfigValidator

        mappings = [
            FieldMapping(path="amount", column="D", type=FieldMappingType.DECIMAL),
            FieldMapping(path="currency", constant="VND", type=FieldMappingType.CONSTANT),
            FieldMapping(path="status", column="F", type=FieldMappingType.STRING),
        ]
        config = _make_config(mappings)

        errors = ConfigValidator.validate_required_coverage(
            config, required_paths={"amount", "currency", "status"}
        )

        assert errors == []

    def test_required_coverage_fails(self):
        """validate_required_coverage() returns error for missing paths."""
        from src.config.validator import ConfigValidator

        mappings = [
            FieldMapping(path="amount", column="D", type=FieldMappingType.DECIMAL),
        ]
        config = _make_config(mappings)

        errors = ConfigValidator.validate_required_coverage(
            config, required_paths={"amount", "currency", "status"}
        )

        assert len(errors) == 2
        missing_paths = {e.field for e in errors}
        assert "currency" in missing_paths
        assert "status" in missing_paths

    def test_required_coverage_with_config_version(self):
        """validate_required_coverage() includes config_version in errors."""
        from src.config.validator import ConfigValidator

        mappings = [
            FieldMapping(path="amount", column="D", type=FieldMappingType.DECIMAL),
        ]
        config = _make_config(mappings, version="v2.0")

        errors = ConfigValidator.validate_required_coverage(
            config, required_paths={"currency"}
        )

        assert len(errors) == 1
        assert errors[0].config_version == "v2.0"


class TestConfigValidatorMultipleErrors:
    """Tests for multiple error detection in single config."""

    def test_multiple_errors_collected(self):
        """validate() collects all errors, not just the first."""
        from src.config.validator import ConfigValidator

        mappings = [
            FieldMapping(path="amount", type=FieldMappingType.CONSTANT),  # CONSTANT without value
            FieldMapping(path="status", type=FieldMappingType.MAPPING),    # MAPPING without dict
            FieldMapping(path="amount", column="D", type=FieldMappingType.DECIMAL),  # duplicate path
        ]
        config = _make_config(mappings)

        errors = ConfigValidator.validate(config)

        # At least: duplicate path + constant without value + mapping without dict
        assert len(errors) >= 3
