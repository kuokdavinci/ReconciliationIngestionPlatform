"""Tests for MongoDB document models and base repository."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from src.core.enums import FileType, ProcessingStatus


class TestReconciliationFile:
    """Tests for ReconciliationFile model."""

    def test_create_with_all_required_fields(self):
        """ReconciliationFile can be instantiated with all required fields."""
        from src.models.reconciliation_file import ReconciliationFile

        now = datetime.now(timezone.utc)
        doc = ReconciliationFile(
            partner="MOMO",
            file_name="test.xlsx",
            file_hash="abc123",
            file_type=FileType.SETTLEMENT,
            reconciliation_date=now,
        )

        assert doc.partner == "MOMO"
        assert doc.file_name == "test.xlsx"
        assert doc.file_hash == "abc123"
        assert doc.file_type == FileType.SETTLEMENT
        assert doc.processing_status == ProcessingStatus.PENDING
        assert doc.total_rows == 0
        assert doc.success_rows == 0
        assert doc.failed_rows == 0
        assert doc.created_by == "system"

    def test_serialization_to_dict(self):
        """ReconciliationFile serializes to dict correctly for MongoDB insertion."""
        from src.models.reconciliation_file import ReconciliationFile

        now = datetime.now(timezone.utc)
        doc = ReconciliationFile(
            partner="MOMO",
            file_name="test.xlsx",
            file_hash="abc123",
            file_type=FileType.SETTLEMENT,
            reconciliation_date=now,
        )

        data = doc.model_dump(by_alias=True)
        assert "partner" in data
        assert "fileName" in data
        assert "fileHash" in data
        assert "fileType" in data
        assert "processingStatus" in data

    def test_file_hash_uniqueness_intent(self):
        """ReconciliationFile.file_hash is used for duplicate detection."""
        from src.models.reconciliation_file import ReconciliationFile

        now = datetime.now(timezone.utc)
        doc1 = ReconciliationFile(
            partner="MOMO",
            file_name="test.xlsx",
            file_hash="same_hash",
            file_type=FileType.SETTLEMENT,
            reconciliation_date=now,
        )
        doc2 = ReconciliationFile(
            partner="VNPAY",
            file_name="other.xlsx",
            file_hash="same_hash",
            file_type=FileType.SETTLEMENT,
            reconciliation_date=now,
        )

        # Both can be created with same hash (uniqueness enforced by DB index)
        assert doc1.file_hash == doc2.file_hash


class TestMappingConfig:
    """Tests for MappingConfig model."""

    def test_create_with_field_mappings(self):
        """MappingConfig accepts list of FieldMapping objects."""
        from src.core.types import FieldMapping, FieldMappingType
        from src.models.mapping_config import MappingConfig

        mappings = [
            FieldMapping(
                path="amount",
                column="D",
                type=FieldMappingType.DECIMAL,
                required=True,
            ),
            FieldMapping(
                path="currency",
                constant="VND",
                type=FieldMappingType.CONSTANT,
            ),
        ]

        doc = MappingConfig(
            partner="MOMO",
            workflow_type="UPC",
            file_type=FileType.SETTLEMENT,
            sheet_name="Sheet1",
            field_mappings=mappings,
        )

        assert doc.partner == "MOMO"
        assert doc.workflow_type == "UPC"
        assert len(doc.field_mappings) == 2
        assert doc.field_mappings[0].path == "amount"
        assert doc.field_mappings[1].constant == "VND"

    def test_serialization_to_dict(self):
        """MappingConfig serializes to dict correctly."""
        from src.core.types import FieldMapping, FieldMappingType
        from src.models.mapping_config import MappingConfig

        doc = MappingConfig(
            partner="MOMO",
            workflow_type="UPC",
            file_type=FileType.SETTLEMENT,
            sheet_name="Sheet1",
            field_mappings=[
                FieldMapping(path="amount", type=FieldMappingType.DECIMAL),
            ],
        )

        data = doc.model_dump(by_alias=True)
        assert "partner" in data
        assert "workflowType" in data
        assert "fieldMappings" in data


class TestDataContainer:
    """Tests for DataContainer and PartnerData models."""

    def test_partner_data_creation(self):
        """PartnerData can be created with all fields."""
        from src.models.data_container import PartnerData

        doc = PartnerData(
            **{"_id": "61838642196"},
            trace="2407055711887385978413624",
            status="SUCCESS",
            amount=Decimal("259200"),
            currency="VND",
        )

        assert doc.id == "61838642196"
        assert doc.trace == "2407055711887385978413624"
        assert doc.status == "SUCCESS"
        assert doc.amount == Decimal("259200")
        assert doc.currency == "VND"

    def test_partner_data_amount_is_decimal(self):
        """PartnerData.amount uses Decimal type (not float)."""
        from src.models.data_container import PartnerData

        doc = PartnerData(
            id="123",
            status="SUCCESS",
            amount=Decimal("100.50"),
            currency="VND",
        )

        assert isinstance(doc.amount, Decimal)

    def test_partner_data_rejects_float_amount(self):
        """PartnerData rejects float amounts for financial correctness."""
        from src.models.data_container import PartnerData

        with pytest.raises(ValidationError):
            PartnerData(
                id="123",
                status="SUCCESS",
                amount=100.50,  # float — should be rejected
                currency="VND",
            )

    def test_data_container_with_nested_partner_data(self):
        """DataContainer.partner_data is a nested PartnerData object (not string)."""
        from src.models.data_container import DataContainer, PartnerData

        partner = PartnerData(
            id="61838642196",
            status="SUCCESS",
            amount=Decimal("259200"),
            currency="VND",
        )

        now = datetime.now(timezone.utc)
        doc = DataContainer(
            identify="MOMO",
            workflow_type="UPC",
            reconciliation_date=now,
            source_file_id=uuid.uuid4(),
            partner_data=partner,
        )

        assert isinstance(doc.partner_data, PartnerData)
        assert doc.partner_data.id == "61838642196"
        assert doc.operation_status == "IN_PROGRESS"
        assert doc.created_by == "system"

    def test_data_container_serialization(self):
        """DataContainer serializes to dict with nested partnerData object."""
        from src.models.data_container import DataContainer, PartnerData

        partner = PartnerData(
            id="61838642196",
            status="SUCCESS",
            amount=Decimal("259200"),
            currency="VND",
            extra={"service": "PAYMENT"},
        )

        now = datetime.now(timezone.utc)
        doc = DataContainer(
            identify="MOMO",
            workflow_type="UPC",
            reconciliation_date=now,
            source_file_id=uuid.uuid4(),
            partner_data=partner,
        )

        data = doc.model_dump(by_alias=True)
        assert "partnerData" in data
        assert isinstance(data["partnerData"], dict)
        assert data["partnerData"]["_id"] == "61838642196"
        assert data["partnerData"]["amount"] == Decimal("259200")


class TestBaseRepository:
    """Tests for BaseRepository class."""

    def test_repository_has_required_methods(self):
        """BaseRepository provides create, find_one, find_many, update_one, delete_one."""
        from src.models.repository import BaseRepository

        assert hasattr(BaseRepository, "create")
        assert hasattr(BaseRepository, "find_one")
        assert hasattr(BaseRepository, "find_many")
        assert hasattr(BaseRepository, "update_one")
        assert hasattr(BaseRepository, "delete_one")

    def test_repository_constructor(self):
        """BaseRepository constructor takes collection_name and database."""
        from src.models.repository import BaseRepository

        mock_db = MagicMock()
        repo = BaseRepository(collection_name="test_collection", db=mock_db)

        assert repo.collection is mock_db.__getitem__.return_value
        mock_db.__getitem__.assert_called_with("test_collection")


class TestReconciliationFileRepository:
    """Tests for ReconciliationFileRepository."""

    def test_has_specialized_methods(self):
        """ReconciliationFileRepository has domain-specific query methods."""
        from src.models.reconciliation_file import ReconciliationFileRepository

        assert hasattr(ReconciliationFileRepository, "find_by_file_hash")
        assert hasattr(ReconciliationFileRepository, "find_by_partner_and_date")
        assert hasattr(ReconciliationFileRepository, "update_processing_stats")
        assert hasattr(ReconciliationFileRepository, "update_status")


class TestMappingConfigRepository:
    """Tests for MappingConfigRepository."""

    def test_has_specialized_methods(self):
        """MappingConfigRepository has domain-specific query methods."""
        from src.models.mapping_config import MappingConfigRepository

        assert hasattr(MappingConfigRepository, "find_by_partner_and_type")
        assert hasattr(MappingConfigRepository, "find_by_version")


class TestDataContainerRepository:
    """Tests for DataContainerRepository."""

    def test_has_specialized_methods(self):
        """DataContainerRepository has domain-specific query methods."""
        from src.models.data_container import DataContainerRepository

        assert hasattr(DataContainerRepository, "find_by_trace")
        assert hasattr(DataContainerRepository, "find_by_source_file")
        assert hasattr(DataContainerRepository, "find_by_date_range")
        assert hasattr(DataContainerRepository, "find_by_duplicate_key")

    @pytest.mark.asyncio
    async def test_find_by_duplicate_key_returns_none_when_no_match(self):
        """find_by_duplicate_key returns None when no matching transaction exists."""
        from unittest.mock import AsyncMock, MagicMock
        from src.models.data_container import DataContainerRepository

        mock_db = MagicMock()
        mock_collection = AsyncMock()
        mock_collection.find_one.return_value = None
        mock_db.__getitem__.return_value = mock_collection

        repo = DataContainerRepository(db=mock_db)
        repo._set_model_class(type("Dummy", (), {"model_validate": lambda self, d: d})())

        rec_date = datetime(2024, 1, 15, tzinfo=timezone.utc)
        result = await repo.find_by_duplicate_key("MOMO", rec_date, "TRACE001")

        assert result is None
        mock_collection.find_one.assert_called_once_with({
            "identify": "MOMO",
            "reconciliationDate": rec_date,
            "partnerData.trace": "TRACE001",
        })

    @pytest.mark.asyncio
    async def test_find_by_duplicate_key_returns_container_when_match(self):
        """find_by_duplicate_key returns DataContainer when a match exists."""
        from unittest.mock import AsyncMock, MagicMock
        from src.models.data_container import DataContainer, DataContainerRepository, PartnerData

        mock_db = MagicMock()
        mock_collection = AsyncMock()

        rec_date = datetime(2024, 1, 15, tzinfo=timezone.utc)
        partner = PartnerData(
            id="61838642196",
            trace="TRACE001",
            status="SUCCESS",
            amount=Decimal("100000"),
            currency="VND",
        )
        existing = DataContainer(
            identify="MOMO",
            workflow_type="UPC",
            reconciliation_date=rec_date,
            source_file_id=uuid.uuid4(),
            partner_data=partner,
        )
        mock_collection.find_one.return_value = existing.model_dump(by_alias=True)

        mock_db.__getitem__.return_value = mock_collection
        repo = DataContainerRepository(db=mock_db)
        repo._set_model_class(DataContainer)

        result = await repo.find_by_duplicate_key("MOMO", rec_date, "TRACE001")

        assert result is not None
        assert isinstance(result, DataContainer)
        assert result.identify == "MOMO"
        assert result.partner_data.trace == "TRACE001"

    def test_has_insert_many_method(self):
        """DataContainerRepository has insert_many method for bulk inserts."""
        from src.models.data_container import DataContainerRepository

        assert hasattr(DataContainerRepository, "insert_many")

    @pytest.mark.asyncio
    async def test_insert_many_calls_collection_insert_many(self):
        """insert_many uses collection.insert_many with serialized documents."""
        from src.models.data_container import DataContainer, DataContainerRepository, PartnerData

        mock_db = MagicMock()
        mock_collection = AsyncMock()
        mock_collection.insert_many.return_value = MagicMock(inserted_ids=[1, 2, 3])
        mock_db.__getitem__.return_value = mock_collection

        repo = DataContainerRepository(db=mock_db)
        repo._set_model_class(DataContainer)

        rec_date = datetime(2024, 1, 15, tzinfo=timezone.utc)
        partner = PartnerData(
            id="txn1",
            status="SUCCESS",
            amount=Decimal("100000"),
            currency="VND",
        )
        docs = [
            DataContainer(
                identify="MOMO",
                workflow_type="UPC",
                reconciliation_date=rec_date,
                source_file_id=uuid.uuid4(),
                partner_data=partner,
            )
            for _ in range(3)
        ]

        count = await repo.insert_many(docs)

        assert count == 3
        mock_collection.insert_many.assert_called_once()
        call_docs = mock_collection.insert_many.call_args[0][0]
        assert len(call_docs) == 3
        # Verify documents are serialized with by_alias
        for doc in call_docs:
            assert "partnerData" in doc
            assert "workflowType" in doc

    @pytest.mark.asyncio
    async def test_insert_many_returns_zero_for_empty_list(self):
        """insert_many returns 0 when given an empty list."""
        from src.models.data_container import DataContainerRepository

        mock_db = MagicMock()
        mock_collection = AsyncMock()
        mock_db.__getitem__.return_value = mock_collection

        repo = DataContainerRepository(db=mock_db)

        count = await repo.insert_many([])

        assert count == 0
        mock_collection.insert_many.assert_not_called()


class TestModelImports:
    """Tests that all model imports work correctly."""

    def test_all_imports(self):
        """All model imports succeed."""
        from src.models.reconciliation_file import (
            ReconciliationFile,
        )
        from src.models.mapping_config import MappingConfig
        from src.models.data_container import (
            DataContainer,
            PartnerData,
        )
        from src.models.repository import BaseRepository

        # Verify they are classes
        assert isinstance(ReconciliationFile, type)
        assert isinstance(MappingConfig, type)
        assert isinstance(DataContainer, type)
        assert isinstance(PartnerData, type)
        assert isinstance(BaseRepository, type)
