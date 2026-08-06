"""Architecture checks for MongoDB index configuration."""

from src.infrastructure.persistence.mongo_indexes import INDEXES, apply_indexes
from src.models.indexes import INDEXES as LegacyIndexes, apply_indexes as legacy_apply_indexes


def test_legacy_indexes_module_is_a_compatibility_facade() -> None:
    """Legacy index imports must resolve to the persistence adapter."""

    assert LegacyIndexes is INDEXES
    assert legacy_apply_indexes is apply_indexes
