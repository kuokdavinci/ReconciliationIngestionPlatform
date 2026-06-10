"""Shared mapping contract normalization and validation helpers."""

from dataclasses import dataclass

from src.config.validator import ConfigValidator
from src.core.constants import DEFAULT_CURRENCY
from src.models.mapping_config import MappingConfig

REQUIRED_MAPPING_PATHS = {"id", "amount", "status"}
STATUS_MAPPING_DEFAULTS = {
    "SUCCESS": "SUCCESS",
    "FAILED": "FAILED",
    "PENDING": "PENDING",
    "REVERSED": "REVERSED",
}


@dataclass(slots=True)
class MappingContractValidation:
    errors: list[str]
    warnings: list[str]

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def score(self) -> int:
        return max(0, min(100, 100 - len(self.errors) * 15 - len(self.warnings) * 5))


def serialize_field_mappings(raw_mappings: list) -> list[dict]:
    serialized: list[dict] = []
    for mapping in raw_mappings:
        if hasattr(mapping, "model_dump"):
            serialized.append(mapping.model_dump(by_alias=True))
        else:
            serialized.append(dict(mapping))
    return serialized


def canonicalize_field_mappings(raw_mappings: list[dict]) -> tuple[list[dict], list[str]]:
    normalized = [dict(item) for item in raw_mappings]
    warnings: list[str] = []
    paths = {item.get("path") for item in normalized if item.get("path")}

    if "currency" not in paths:
        normalized.append(
            {
                "path": "currency",
                "type": "CONSTANT",
                "constant": DEFAULT_CURRENCY,
                "required": True,
            }
        )
        warnings.append(
            f"Currency was not mapped, so a CONSTANT '{DEFAULT_CURRENCY}' mapping was added."
        )

    for item in normalized:
        if item.get("path") == "status" and str(item.get("type", "")).upper() == "STRING":
            item["type"] = "MAPPING"
            item["mapping"] = dict(STATUS_MAPPING_DEFAULTS)
            warnings.append(
                "Status mapping was upgraded from STRING to MAPPING. Adjust status normalization if partner values differ."
            )

    return normalized, warnings


def validate_mapping_contract(
    config: MappingConfig,
    required_paths: set[str] = REQUIRED_MAPPING_PATHS,
) -> MappingContractValidation:
    errors = [err.reason for err in ConfigValidator.validate(config)]
    errors.extend(
        err.reason for err in ConfigValidator.validate_required_coverage(config, required_paths)
    )

    warnings: list[str] = []
    source_cols: dict[int | str, list[str]] = {}
    for field_mapping in config.field_mappings:
        if field_mapping.column is not None:
            source_cols.setdefault(field_mapping.column, []).append(field_mapping.path)
        if field_mapping.column is None and field_mapping.constant is None:
            warnings.append(
                f"Field '{field_mapping.path}' has neither a source column nor a constant value."
            )

    for col, paths in source_cols.items():
        if len(paths) > 1:
            warnings.append(f"Column {col} is mapped to multiple fields: {', '.join(paths)}")

    return MappingContractValidation(errors=errors, warnings=warnings)
