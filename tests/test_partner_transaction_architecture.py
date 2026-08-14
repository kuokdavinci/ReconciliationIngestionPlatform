from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import src.core.types as core_types
from src.domain.partner_transaction.models import DataContainer, PartnerData
from src.infrastructure.partner_transaction.repository import DataContainerRepository


def test_core_types_does_not_define_partner_data():
    source = Path(core_types.__file__).read_text()

    assert "class PartnerData" not in source


def test_partner_transaction_domain_and_adapter_have_separate_ownership():
    assert DataContainer.__module__ == "src.domain.partner_transaction.models"
    assert PartnerData.__module__ == "src.domain.partner_transaction.models"
    assert DataContainerRepository.__module__ == "src.infrastructure.partner_transaction.repository"


def test_partner_transaction_repository_accepts_explicit_postgres_engine():
    engine = MagicMock()

    repository = DataContainerRepository(engine=engine)

    assert repository.engine is engine


@pytest.mark.asyncio
async def test_copy_records_uses_conflict_safe_insert():
    document = DataContainer(
        identify="MOMO",
        workflow_type="UPC",
        reconciliation_date=datetime.now(timezone.utc),
        source_file_id=uuid4(),
        partner_data=PartnerData(
            _id="txn-1",
            trace="trace-1",
            status="SUCCESS",
            amount=Decimal("10"),
            currency="VND",
        ),
    )
    repository = DataContainerRepository(engine=MagicMock())
    repository._insert_rows_conflict_safe = AsyncMock(return_value=1)

    inserted = await repository.copy_records([document])

    assert inserted == 1
    repository._insert_rows_conflict_safe.assert_awaited_once()
