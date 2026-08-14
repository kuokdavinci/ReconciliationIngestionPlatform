"""PostgreSQL acceptance coverage for Plan 1 idempotency."""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
import asyncpg
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import create_async_engine

from src.config.settings import settings
from src.domain.partner_transaction.models import DataContainer, PartnerData
from src.infrastructure.partner_transaction.repository import DataContainerRepository
from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable


pytestmark = pytest.mark.integration


def _transaction(identify: str, key: str) -> DataContainer:
    return DataContainer(
        identify=identify,
        workflowType="UPC",
        reconciliationDate=datetime(2024, 1, 15, tzinfo=timezone.utc),
        sourceFileId=uuid4(),
        ingestionKey=key,
        partnerData=PartnerData(
            _id=key,
            trace=f"TRACE-{key}",
            status="SUCCESS",
            amount=Decimal("100.00"),
            currency="VND",
        ),
    )


@pytest.mark.asyncio
async def test_plan1_postgres_transaction_idempotency_matrix():
    """Verify insert, mixed replay, full replay and distinct keys on real PostgreSQL."""
    try:
        connection = await asyncio.wait_for(
            asyncpg.connect(settings.postgres_url.replace("+asyncpg", "")),
            timeout=3,
        )
        await connection.close()
    except Exception as exc:
        pytest.skip(f"PostgreSQL is not available at {settings.postgres_url}: {exc}")
    engine = create_async_engine(settings.postgres_url)

    identify = f"PLAN1_IT_{uuid4().hex}"
    repo = DataContainerRepository(engine=engine)
    first = [_transaction(identify, f"KEY-{index}") for index in range(2)]
    mixed = [first[0], _transaction(identify, "KEY-2")]
    full_replay = [_transaction(identify, f"KEY-{index}") for index in range(3)]
    distinct = _transaction(identify, "KEY-3")

    try:
        initial = await repo.insert_many(first, detailed=True)
        assert (initial.inserted, initial.duplicates, initial.failed) == (2, 0, 0)

        partial = await repo.insert_many(mixed, detailed=True)
        assert (partial.inserted, partial.duplicates, partial.failed) == (1, 1, 0)

        replay = await repo.insert_many(full_replay, detailed=True)
        assert (replay.inserted, replay.duplicates, replay.failed) == (0, 3, 0)

        separate = await repo.insert_many([distinct], detailed=True)
        assert (separate.inserted, separate.duplicates, separate.failed) == (1, 0, 0)

        async with engine.connect() as connection:
            count = await connection.scalar(
                select(func.count())
                .select_from(PartnerTransactionTable)
                .where(PartnerTransactionTable.identify == identify)
            )
        assert count == 4
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                delete(PartnerTransactionTable).where(
                    PartnerTransactionTable.identify == identify
                )
            )
        await engine.dispose()
