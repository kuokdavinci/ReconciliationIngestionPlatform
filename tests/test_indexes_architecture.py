"""Architecture checks for MongoDB index configuration."""

import src.infrastructure.persistence.mongo_indexes as mongo_indexes
from src.infrastructure.persistence.mongo_indexes import INDEXES, apply_indexes


def test_indexes_are_owned_by_persistence_infrastructure() -> None:
    assert mongo_indexes.__name__ == "src.infrastructure.persistence.mongo_indexes"
    assert apply_indexes.__globals__["INDEXES"] is INDEXES
    assert apply_indexes.__module__ == "src.infrastructure.persistence.mongo_indexes"
