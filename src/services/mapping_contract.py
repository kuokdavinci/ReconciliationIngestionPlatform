"""Compatibility facade for the domain mapping contract."""

from src.domain.mapping.contract import (
    MappingContractValidation,
    canonicalize_field_mappings,
    serialize_field_mappings,
    validate_mapping_contract,
)

__all__ = [
    "MappingContractValidation",
    "canonicalize_field_mappings",
    "serialize_field_mappings",
    "validate_mapping_contract",
]
