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
        from src.domain.ingestion.models import ReconciliationFile

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
        from src.domain.ingestion.models import ReconciliationFile

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
        from src.domain.ingestion.models import ReconciliationFile

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
        from src.domain.mapping.models import MappingConfig

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
        from src.domain.mapping.models import MappingConfig

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
        from src.domain.partner_transaction.models import PartnerData

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
        from src.domain.partner_transaction.models import PartnerData

        doc = PartnerData(
            id="123",
            status="SUCCESS",
            amount=Decimal("100.50"),
            currency="VND",
        )

        assert isinstance(doc.amount, Decimal)

    def test_partner_data_rejects_float_amount(self):
        """PartnerData rejects float amounts for financial correctness."""
        from src.domain.partner_transaction.models import PartnerData

        with pytest.raises(ValidationError):
            PartnerData(
                id="123",
                status="SUCCESS",
                amount=100.50,  # float — should be rejected
                currency="VND",
            )

    def test_data_container_with_nested_partner_data(self):
        """DataContainer.partner_data is a nested PartnerData object (not string)."""
        from src.domain.partner_transaction.models import DataContainer, PartnerData

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
        from src.domain.partner_transaction.models import DataContainer, PartnerData

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
        from src.infrastructure.persistence.mongo_repository import BaseRepository

        assert hasattr(BaseRepository, "create")
        assert hasattr(BaseRepository, "find_one")
        assert hasattr(BaseRepository, "find_many")
        assert hasattr(BaseRepository, "update_one")
        assert hasattr(BaseRepository, "delete_one")

    def test_repository_constructor(self):
        """BaseRepository constructor takes collection_name and database."""
        from src.infrastructure.persistence.mongo_repository import BaseRepository

        mock_db = MagicMock()
        repo = BaseRepository(collection_name="test_collection", db=mock_db)

        assert repo.collection is mock_db.__getitem__.return_value
        mock_db.__getitem__.assert_called_with("test_collection")


class TestReconciliationFileRepository:
    """Tests for ReconciliationFileRepository."""

    def test_has_specialized_methods(self):
        """ReconciliationFileRepository has domain-specific query methods."""
        from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository

        assert hasattr(ReconciliationFileRepository, "find_by_file_hash")
        assert hasattr(ReconciliationFileRepository, "create_or_get_by_file_hash")
        assert hasattr(ReconciliationFileRepository, "find_by_partner_and_date")
        assert hasattr(ReconciliationFileRepository, "update_processing_stats")
        assert hasattr(ReconciliationFileRepository, "update_status")

    @pytest.mark.asyncio
    async def test_create_or_get_by_file_hash_returns_existing_on_duplicate(self):
        from pymongo.errors import DuplicateKeyError
        from src.domain.ingestion.models import ReconciliationFile
        from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository

        mock_db = MagicMock()
        mock_collection = AsyncMock()
        mock_collection.insert_one.side_effect = DuplicateKeyError("E11000 duplicate key error")

        now = datetime.now(timezone.utc)
        existing = ReconciliationFile(
            partner="MOMO",
            file_name="test.xlsx",
            file_hash="same_hash",
            file_type=FileType.SETTLEMENT,
            reconciliation_date=now,
        )
        mock_collection.find_one.return_value = existing.model_dump(by_alias=True)
        mock_db.__getitem__.return_value = mock_collection

        repo = ReconciliationFileRepository(db=mock_db)
        repo._set_model_class(ReconciliationFile)

        created, is_created = await repo.create_or_get_by_file_hash(
            ReconciliationFile(
                partner="MOMO",
                file_name="test.xlsx",
                file_hash="same_hash",
                file_type=FileType.SETTLEMENT,
                reconciliation_date=now,
            )
        )

        assert is_created is False
        assert created.file_hash == "same_hash"
        mock_collection.insert_one.assert_called_once()
        mock_collection.find_one.assert_called_once_with({"fileHash": "same_hash"})

    @pytest.mark.asyncio
    async def test_create_or_get_by_file_hash_inserts_new_record(self):
        from src.domain.ingestion.models import ReconciliationFile
        from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository

        mock_db = MagicMock()
        mock_collection = AsyncMock()
        mock_collection.insert_one.return_value = MagicMock(inserted_id="new-id")
        mock_db.__getitem__.return_value = mock_collection

        repo = ReconciliationFileRepository(db=mock_db)
        repo._set_model_class(ReconciliationFile)
        now = datetime.now(timezone.utc)
        doc = ReconciliationFile(
            partner="MOMO",
            file_name="test.xlsx",
            file_hash="hash-new",
            file_type=FileType.SETTLEMENT,
            reconciliation_date=now,
        )

        created, is_created = await repo.create_or_get_by_file_hash(doc)

        assert is_created is True
        assert created.file_hash == "hash-new"
        mock_collection.insert_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_or_get_resolves_fetch_unit_duplicate(self):
        from pymongo.errors import DuplicateKeyError
        from src.domain.ingestion.models import ReconciliationFile
        from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository

        mock_db = MagicMock()
        mock_collection = AsyncMock()
        mock_collection.insert_one.side_effect = DuplicateKeyError("duplicate fetch unit")
        now = datetime.now(timezone.utc)
        existing = ReconciliationFile(
            partner="MOMO",
            file_name="page-1-old.xlsx",
            file_hash="old-content",
            file_type=FileType.SETTLEMENT,
            reconciliation_date=now,
            fetch_unit_key="fetch-key",
        )
        mock_collection.find_one.side_effect = [
            None,
            existing.model_dump(by_alias=True),
        ]
        mock_db.__getitem__.return_value = mock_collection
        repo = ReconciliationFileRepository(db=mock_db)

        canonical, created = await repo.create_or_get_by_file_hash(
            ReconciliationFile(
                partner="MOMO",
                file_name="page-1-new.xlsx",
                file_hash="new-content",
                file_type=FileType.SETTLEMENT,
                reconciliation_date=now,
                fetch_unit_key="fetch-key",
            )
        )

        assert created is False
        assert canonical.file_hash == "old-content"
        assert mock_collection.find_one.await_args_list[1].args[0] == {"fetchUnitKey": "fetch-key"}

    @pytest.mark.asyncio
    async def test_concurrent_file_claim_has_one_canonical_winner(self):
        import asyncio
        from pymongo.errors import DuplicateKeyError
        from src.domain.ingestion.models import ReconciliationFile
        from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository

        mock_db = MagicMock()
        mock_collection = AsyncMock()
        mock_collection.insert_one.side_effect = [
            MagicMock(inserted_id="winner"),
            DuplicateKeyError("duplicate file hash"),
        ]
        now = datetime.now(timezone.utc)
        canonical = ReconciliationFile(
            partner="MOMO",
            file_name="same.xlsx",
            file_hash="same-hash",
            file_type=FileType.SETTLEMENT,
            reconciliation_date=now,
        )
        mock_collection.find_one.return_value = canonical.model_dump(by_alias=True)
        mock_db.__getitem__.return_value = mock_collection
        repo = ReconciliationFileRepository(db=mock_db)

        results = await asyncio.gather(
            repo.create_or_get_by_file_hash(canonical.model_copy(deep=True)),
            repo.create_or_get_by_file_hash(canonical.model_copy(deep=True)),
        )

        assert sorted(created for _, created in results) == [False, True]
        assert {record.file_hash for record, _ in results} == {"same-hash"}


class TestMappingConfigRepository:
    """Tests for MappingConfigRepository."""

    def test_has_specialized_methods(self):
        """MappingConfigRepository has domain-specific query methods."""
        from src.infrastructure.mapping.config_repository import MappingConfigRepository

        assert hasattr(MappingConfigRepository, "find_by_partner_and_type")
        assert hasattr(MappingConfigRepository, "find_by_version")


class TestDataContainerRepository:
    def test_has_specialized_methods(self):
        from src.infrastructure.partner_transaction.repository import DataContainerRepository

        assert hasattr(DataContainerRepository, "find_by_trace")
        assert hasattr(DataContainerRepository, "find_by_ingestion_key")
        assert hasattr(DataContainerRepository, "find_by_source_file")
        assert hasattr(DataContainerRepository, "find_by_date_range")
        assert hasattr(DataContainerRepository, "find_by_duplicate_key")
        assert hasattr(DataContainerRepository, "delete_by_source_file")

    def test_repository_uses_explicit_postgres_engine(self):
        from src.infrastructure.partner_transaction.repository import DataContainerRepository

        engine = object()
        repo = DataContainerRepository(db=MagicMock(), engine=engine)

        assert repo.engine is engine
        assert not hasattr(repo, "collection")

    @pytest.mark.asyncio
    async def test_insert_many_returns_zero_for_empty_list(self):
        from src.infrastructure.partner_transaction.repository import DataContainerRepository
        from src.domain.partner_transaction.duplicates import BatchWriteResult

        repo = DataContainerRepository(engine=object())

        assert await repo.insert_many([]) == BatchWriteResult(inserted=0)


class TestDataContainerIngestionKey:
    def test_ingestion_key_roundtrip_via_row_helpers(self):
        from src.domain.partner_transaction.models import DataContainer, PartnerData
        from src.infrastructure.partner_transaction.repository import (
            data_container_to_row,
            row_to_data_container,
        )

        now = datetime.now(timezone.utc)
        partner = PartnerData(
            id="TXN001",
            trace="TRACE001",
            status="SUCCESS",
            amount=Decimal("100000"),
            currency="VND",
        )
        doc = DataContainer(
            identify="MOMO",
            workflow_type="UPC",
            reconciliation_date=now,
            source_file_id=uuid.uuid4(),
            partner_data=partner,
            ingestion_key="MOMO:TXN001",
        )
        row = data_container_to_row(doc)
        assert row["ingestion_key"] == "MOMO:TXN001"
        restored = row_to_data_container(row)
        assert restored.ingestion_key == "MOMO:TXN001"
        assert restored.partner_data.id == "TXN001"


class TestModelImports:
    """Tests that all model imports work correctly."""

    def test_all_imports(self):
        """All model imports succeed."""
        from src.domain.ingestion.models import (
            ReconciliationFile,
        )
        from src.domain.mapping.models import MappingConfig
        from src.domain.partner_transaction.models import (
            DataContainer,
            PartnerData,
        )
        from src.infrastructure.persistence.mongo_repository import BaseRepository

        # Verify they are classes
        assert isinstance(ReconciliationFile, type)
        assert isinstance(MappingConfig, type)
        assert isinstance(DataContainer, type)
        assert isinstance(PartnerData, type)
        assert isinstance(BaseRepository, type)


class TestPostgresSchema:
    def test_partner_transaction_has_unique_identity_constraint(self):
        from sqlalchemy import UniqueConstraint
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable

        unique_constraints = [
            constraint
            for constraint in PartnerTransactionTable.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        ]

        assert any(
            tuple(constraint.columns.keys()) == ("identify", "ingestion_key")
            for constraint in unique_constraints
        )
