"""Compatibility facade for MongoDB index definitions."""

from src.infrastructure.persistence.mongo_indexes import INDEXES, apply_indexes

__all__ = ["INDEXES", "apply_indexes"]
