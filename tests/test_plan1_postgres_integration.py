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
from tests.postgres_probe import postgres_dsn_if_available, postgres_url_for_tests


pytestmark = pytest.mark.integration


def _transaction(
    identify: str,
    key: str,
    *,
    amount: Decimal = Decimal("100.00"),
) -> DataContainer:
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
            amount=amount,
            currency="VND",
        ),
    )


async def _postgres_url_or_skip() -> str:
    database_url = postgres_url_for_tests(settings.postgres_url)
    dsn = await postgres_dsn_if_available(settings.postgres_url)
    if dsn is None:
        pytest.skip(f"PostgreSQL is not available at {database_url}")
    try:
        connection = await asyncpg.connect(dsn, timeout=3)
    except Exception as exc:
        pytest.skip(f"PostgreSQL credentials are not usable at {database_url}: {exc}")
    await connection.close()
    return database_url


@pytest.mark.asyncio
async def test_plan1_postgres_transaction_idempotency_matrix():
    """Verify insert, mixed replay, full replay and distinct keys on real PostgreSQL."""
    database_url = await _postgres_url_or_skip()
    engine = create_async_engine(database_url)

    identify = f"PLAN1_IT_{uuid4().hex}"
    repo = DataContainerRepository(engine=engine)
    first = [_transaction(identify, f"KEY-{index}") for index in range(2)]
    mixed = [first[0], _transaction(identify, "KEY-2")]
    full_replay = [_transaction(identify, f"KEY-{index}") for index in range(3)]
    distinct = _transaction(identify, "KEY-3")

    try:
        initial = await repo.insert_many(first)
        assert (initial.inserted, initial.duplicates, initial.failed) == (2, 0, 0)

        partial = await repo.insert_many(mixed)
        assert (partial.inserted, partial.duplicates, partial.failed) == (1, 1, 0)
        assert (partial.equivalent_duplicates, partial.conflicting_duplicates) == (1, 0)

        replay = await repo.insert_many(full_replay)
        assert (replay.inserted, replay.duplicates, replay.failed) == (0, 3, 0)
        assert (replay.equivalent_duplicates, replay.conflicting_duplicates) == (3, 0)

        separate = await repo.insert_many([distinct])
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
                delete(PartnerTransactionTable).where(PartnerTransactionTable.identify == identify)
            )
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_same_payload_insert_is_classified_without_a_race():
    """One atomic winner and one equivalent duplicate are observed under contention."""
    database_url = await _postgres_url_or_skip()
    engine = create_async_engine(database_url)
    identify = f"QUALITY_RACE_{uuid4().hex}"
    key = "SAME-KEY"
    repository = DataContainerRepository(engine=engine)

    try:
        first, second = await asyncio.gather(
            repository.insert_many([_transaction(identify, key)]),
            repository.insert_many([_transaction(identify, key)]),
        )

        assert first.inserted + second.inserted == 1
        assert first.duplicates + second.duplicates == 1
        assert first.equivalent_duplicates + second.equivalent_duplicates == 1
        assert first.conflicting_duplicates + second.conflicting_duplicates == 0
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                delete(PartnerTransactionTable).where(PartnerTransactionTable.identify == identify)
            )
        await engine.dispose()


@pytest.mark.asyncio
async def test_intra_batch_conflict_preserves_the_incoming_row_ordinal():
    database_url = await _postgres_url_or_skip()
    engine = create_async_engine(database_url)
    identify = f"QUALITY_ORDINAL_{uuid4().hex}"
    key = "SAME-KEY"
    repository = DataContainerRepository(engine=engine)

    try:
        result = await repository.insert_many(
            [
                _transaction(identify, key, amount=Decimal("100")),
                _transaction(identify, key, amount=Decimal("200")),
            ]
        )

        assert result.inserted == 1
        assert result.conflicting_duplicates == 1
        assert result.duplicate_details[0].incoming_index == 1
        async with engine.connect() as connection:
            stored_amount = await connection.scalar(
                select(PartnerTransactionTable.partner_amount).where(
                    PartnerTransactionTable.identify == identify,
                    PartnerTransactionTable.ingestion_key == key,
                )
            )
        assert stored_amount == Decimal("100")
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                delete(PartnerTransactionTable).where(PartnerTransactionTable.identify == identify)
            )
        await engine.dispose()


async def test_large_equivalent_duplicate_batch_uses_scalable_conflict_lookup():
    """Bulk conflict lookup must not expand into a stack-depth-sized IN expression."""
    database_url = await _postgres_url_or_skip()
    engine = create_async_engine(database_url)
    identify = f"QUALITY_LARGE_REPLAY_{uuid4().hex}"
    repository = DataContainerRepository(engine=engine)
    initial = [_transaction(identify, f"KEY-{index}") for index in range(10_000)]
    replay = [_transaction(identify, f"KEY-{index}") for index in range(10_000)]

    try:
        inserted = await repository.insert_many(initial)
        assert inserted.inserted == 10_000

        result = await repository.insert_many(replay)

        assert result.inserted == 0
        assert result.duplicates == 10_000
        assert result.equivalent_duplicates == 10_000
        assert result.conflicting_duplicates == 0
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                delete(PartnerTransactionTable).where(PartnerTransactionTable.identify == identify)
            )
        await engine.dispose()
