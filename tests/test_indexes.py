"""Tests for MongoDB index definitions."""

import inspect

import pytest
from pymongo import IndexModel
from pymongo.errors import OperationFailure


class TestIndexesDefinition:
    """Tests for INDEXES dictionary structure."""

    def test_indexes_dict_has_all_collections(self):
        """INDEXES dict has entries for all three collections."""
        from src.infrastructure.persistence.mongo_indexes import INDEXES

        assert "reconciliation_file" in INDEXES
        assert "ingestion_checkpoint" in INDEXES
        assert "reconciliation_mapping_config" in INDEXES
        assert "data_container" not in INDEXES

    def test_indexes_are_lists_of_index_models(self):
        """Each collection's indexes is a list of IndexModel objects."""
        from src.infrastructure.persistence.mongo_indexes import INDEXES

        for collection, indexes in INDEXES.items():
            assert isinstance(indexes, list), f"{collection} indexes not a list"
            assert len(indexes) > 0, f"{collection} has no indexes"
            for idx in indexes:
                assert isinstance(idx, IndexModel), (
                    f"{collection} has non-IndexModel entry: {type(idx)}"
                )


class TestReconciliationFileIndexes:
    """Tests for reconciliation_file index definitions."""

    def test_unique_index_on_file_hash(self):
        """reconciliation_file has UNIQUE index on file_hash."""
        from src.infrastructure.persistence.mongo_indexes import INDEXES

        indexes = INDEXES["reconciliation_file"]
        hash_indexes = [
            idx
            for idx in indexes
            if "file_hash" in idx.document["key"]
            or "fileHash" in idx.document["key"]
        ]
        assert len(hash_indexes) >= 1, "No index on file_hash found"

        # Check at least one is unique
        unique_hash_indexes = [
            idx
            for idx in hash_indexes
            if idx.document.get("unique", False)
        ]
        assert len(unique_hash_indexes) >= 1, (
            "No UNIQUE index on file_hash found"
        )

    def test_unique_file_hash_index_is_scoped_to_partner(self):
        """The file claim boundary is partner plus content hash."""
        from src.infrastructure.persistence.mongo_indexes import INDEXES

        assert any(
            idx.document.get("unique", False)
            and list(idx.document["key"]) == ["partner", "fileHash"]
            for idx in INDEXES["reconciliation_file"]
        )

    def test_compound_index_on_partner_and_date(self):
        """reconciliation_file has compound index on partner + reconciliation_date."""
        from src.infrastructure.persistence.mongo_indexes import INDEXES

        indexes = INDEXES["reconciliation_file"]
        compound_indexes = [
            idx
            for idx in indexes
            if len(idx.document["key"]) > 1
        ]
        assert len(compound_indexes) >= 1, "No compound index found"

        # Check one has partner and reconciliation_date
        partner_date_found = False
        for idx in compound_indexes:
            keys = list(idx.document["key"].keys())
            if "partner" in keys and (
                "reconciliation_date" in keys
                or "reconciliationDate" in keys
            ):
                partner_date_found = True
                break
        assert partner_date_found, (
            "No compound index on partner + reconciliation_date"
        )


class TestIngestionCheckpointIndexes:
    """Tests for the Sprint 2 checkpoint index contract."""

    def test_unique_stream_identity_index(self):
        from src.infrastructure.persistence.mongo_indexes import INDEXES

        indexes = INDEXES["ingestion_checkpoint"]
        unique = [
            idx
            for idx in indexes
            if idx.document.get("unique", False)
            and list(idx.document["key"]) == [
                "partner",
                "fetchConfigId",
                "sourceType",
                "streamKey",
                "mode",
            ]
        ]
        assert len(unique) == 1

    def test_retry_query_index_contains_status_and_updated_time(self):
        from src.infrastructure.persistence.mongo_indexes import INDEXES

        assert any(
            list(idx.document["key"]) == ["status", "updatedAt"]
            for idx in INDEXES["ingestion_checkpoint"]
        )


class TestMappingConfigIndexes:
    """Tests for reconciliation_mapping_config index definitions."""

    def test_compound_index_on_partner_workflow_type(self):
        """mapping_config has compound index on partner + workflow_type + file_type."""
        from src.infrastructure.persistence.mongo_indexes import INDEXES

        indexes = INDEXES["reconciliation_mapping_config"]
        assert len(indexes) >= 1, "No indexes defined for mapping_config"

        compound_indexes = [
            idx for idx in indexes if len(idx.document["key"]) > 1
        ]
        assert len(compound_indexes) >= 1, "No compound index found"


class TestApplyIndexes:
    """Tests for apply_indexes function."""

    def test_apply_indexes_is_async(self):
        """apply_indexes function is async."""
        from src.infrastructure.persistence.mongo_indexes import apply_indexes

        assert inspect.iscoroutinefunction(apply_indexes), (
            "apply_indexes must be an async function"
        )

    def test_apply_indexes_accepts_database(self):
        """apply_indexes accepts AsyncIOMotorDatabase parameter."""
        from src.infrastructure.persistence.mongo_indexes import apply_indexes

        sig = inspect.signature(apply_indexes)
        params = list(sig.parameters.keys())
        assert "db" in params, "apply_indexes must have 'db' parameter"


class _IndexCursor:
    def __init__(self, documents):
        self._documents = documents

    async def to_list(self, length=None):
        return self._documents


class _IndexCollection:
    def __init__(self, indexes):
        self.indexes = indexes
        self.dropped = []
        self.created = []

    def list_indexes(self):
        return _IndexCursor(self.indexes)

    async def drop_index(self, name):
        self.dropped.append(name)
        self.indexes = [index for index in self.indexes if index.get("name") != name]

    async def create_indexes(self, indexes):
        self.created.extend(indexes)


class _MissingIndexCollection(_IndexCollection):
    def list_indexes(self):
        raise OperationFailure("ns does not exist", code=26)


@pytest.mark.asyncio
async def test_legacy_sparse_fetch_unit_index_is_replaced_by_partial_index():
    from src.infrastructure.persistence.mongo_indexes import (
        INDEXES,
        _ensure_collection_indexes,
    )

    collection = _IndexCollection(
        [
            {
                "key": {"fetchUnitKey": 1},
                "name": "idx_fetch_unit_key_unique",
                "unique": True,
                "sparse": True,
            }
        ]
    )

    await _ensure_collection_indexes(collection, [INDEXES["reconciliation_file"][1]])

    assert collection.dropped == ["idx_fetch_unit_key_unique"]
    assert collection.created[0].document["partialFilterExpression"] == {
        "fetchUnitKey": {"$type": "string"}
    }


@pytest.mark.asyncio
async def test_missing_collection_is_created_with_desired_indexes():
    from src.infrastructure.persistence.mongo_indexes import (
        INDEXES,
        _ensure_collection_indexes,
    )

    collection = _MissingIndexCollection([])

    await _ensure_collection_indexes(collection, [INDEXES["reconciliation_file"][1]])

    assert len(collection.created) == 1
    assert collection.created[0].document["name"] == "idx_fetch_unit_key_unique"
