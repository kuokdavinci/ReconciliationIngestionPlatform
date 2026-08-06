"""Regression coverage for PostgreSQL startup migrations."""

from uuid import uuid4

import asyncpg
import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.config.settings import settings
from src.models.postgres import _alembic_config, init_postgres_db


pytestmark = pytest.mark.integration


def _without_asyncpg_scheme(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


@pytest.mark.asyncio
async def test_existing_revision_0001_is_upgraded_to_head():
    """Startup must apply 0002 when an existing database is at revision 0001."""
    configured_url = _without_asyncpg_scheme(settings.postgres_url)
    server_url, _ = configured_url.rsplit("/", 1)
    database_name = f"migration_test_{uuid4().hex}"
    admin_url = f"{server_url}/postgres"
    database_url = f"{server_url}/{database_name}"
    admin_connection = None
    database_engine = None

    try:
        try:
            admin_connection = await asyncpg.connect(admin_url, timeout=3)
        except Exception as exc:
            pytest.skip(f"PostgreSQL is not available at {admin_url}: {exc}")

        await admin_connection.execute(f"CREATE DATABASE {database_name}")
        await admin_connection.close()
        admin_connection = None

        database_engine = create_async_engine(database_url.replace("postgresql://", "postgresql+asyncpg://", 1))
        async with database_engine.begin() as connection:
            def upgrade_to_0001(sync_connection):
                config = _alembic_config(sync_connection)
                config.attributes["connection"] = sync_connection
                command.upgrade(config, "0001")

            await connection.run_sync(upgrade_to_0001)
        await database_engine.dispose()
        database_engine = None

        await init_postgres_db(database_url)

        database_engine = create_async_engine(database_url.replace("postgresql://", "postgresql+asyncpg://", 1))
        async with database_engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            has_ingestion_key = await connection.scalar(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'partner_transaction' AND column_name = 'ingestion_key'"
                    ")"
                )
            )
            has_unique_constraint = await connection.scalar(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM pg_constraint "
                    "WHERE conname = 'uq_partner_transaction_identify_ingestion_key'"
                    ")"
                )
            )

        assert revision == "0002"
        assert has_ingestion_key is True
        assert has_unique_constraint is True
    finally:
        if database_engine is not None:
            await database_engine.dispose()
        if admin_connection is None:
            try:
                admin_connection = await asyncpg.connect(admin_url, timeout=3)
            except Exception:
                admin_connection = None
        if admin_connection is not None:
            await admin_connection.execute(f"DROP DATABASE IF EXISTS {database_name}")
            await admin_connection.close()
