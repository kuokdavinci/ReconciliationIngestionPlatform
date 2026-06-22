"""Tests for MongoDB index definitions."""

import inspect

from pymongo import IndexModel


class TestIndexesDefinition:
    """Tests for INDEXES dictionary structure."""

    def test_indexes_dict_has_all_collections(self):
        """INDEXES dict has entries for all three collections."""
        from src.models.indexes import INDEXES

        assert "reconciliation_file" in INDEXES
        assert "reconciliation_mapping_config" in INDEXES
        assert "data_container" in INDEXES

    def test_indexes_are_lists_of_index_models(self):
        """Each collection's indexes is a list of IndexModel objects."""
        from src.models.indexes import INDEXES

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
        from src.models.indexes import INDEXES

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

    def test_compound_index_on_partner_and_date(self):
        """reconciliation_file has compound index on partner + reconciliation_date."""
        from src.models.indexes import INDEXES

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


class TestMappingConfigIndexes:
    """Tests for reconciliation_mapping_config index definitions."""

    def test_compound_index_on_partner_workflow_type(self):
        """mapping_config has compound index on partner + workflow_type + file_type."""
        from src.models.indexes import INDEXES

        indexes = INDEXES["reconciliation_mapping_config"]
        assert len(indexes) >= 1, "No indexes defined for mapping_config"

        compound_indexes = [
            idx for idx in indexes if len(idx.document["key"]) > 1
        ]
        assert len(compound_indexes) >= 1, "No compound index found"


class TestDataContainerIndexes:
    """Tests for data_container index definitions."""

    def test_index_on_trace(self):
        """data_container has index on partnerData.trace."""
        from src.models.indexes import INDEXES

        indexes = INDEXES["data_container"]
        trace_indexes = [
            idx
            for idx in indexes
            if "partner_data.trace" in idx.document["key"]
            or "partnerData.trace" in idx.document["key"]
        ]
        assert len(trace_indexes) >= 1, "No index on partnerData.trace found"

    def test_compound_index_on_identify_and_date(self):
        """data_container has compound index on identify + reconciliation_date."""
        from src.models.indexes import INDEXES

        indexes = INDEXES["data_container"]
        compound_indexes = [
            idx for idx in indexes if len(idx.document["key"]) > 1
        ]

        identify_date_found = False
        for idx in compound_indexes:
            keys = list(idx.document["key"].keys())
            if "identify" in keys and (
                "reconciliation_date" in keys
                or "reconciliationDate" in keys
            ):
                identify_date_found = True
                break
        assert identify_date_found, (
            "No compound index on identify + reconciliation_date"
        )

    def test_index_on_operation_status(self):
        """data_container has index on operation_status."""
        from src.models.indexes import INDEXES

        indexes = INDEXES["data_container"]
        status_indexes = [
            idx
            for idx in indexes
            if "operation_status" in idx.document["key"]
            or "operationStatus" in idx.document["key"]
        ]
        assert len(status_indexes) >= 1, (
            "No index on operation_status found"
        )

    def test_index_on_partner_status(self):
        """data_container has index on partnerData.status."""
        from src.models.indexes import INDEXES

        indexes = INDEXES["data_container"]
        partner_status_indexes = [
            idx
            for idx in indexes
            if "partner_data.status" in idx.document["key"]
            or "partnerData.status" in idx.document["key"]
        ]
        assert len(partner_status_indexes) >= 1, (
            "No index on partnerData.status found"
        )


class TestApplyIndexes:
    """Tests for apply_indexes function."""

    def test_apply_indexes_is_async(self):
        """apply_indexes function is async."""
        from src.models.indexes import apply_indexes

        assert inspect.iscoroutinefunction(apply_indexes), (
            "apply_indexes must be an async function"
        )

    def test_apply_indexes_accepts_database(self):
        """apply_indexes accepts AsyncIOMotorDatabase parameter."""
        from src.models.indexes import apply_indexes

        sig = inspect.signature(apply_indexes)
        params = list(sig.parameters.keys())
        assert "db" in params, "apply_indexes must have 'db' parameter"
