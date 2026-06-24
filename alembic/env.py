"""Alembic environment configuration with async SQLAlchemy support.

Supports two modes:
1. CLI/standalone: creates its own async engine via asyncio.run()
2. Programmatic: uses a pre-existing connection from config.attributes['connection']
"""
import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# Ensure the project root is on sys.path so `src` can be imported
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models.postgres import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Support pre-existing connection for programmatic use (e.g., FastAPI lifespan)
target_connection = config.attributes.get('connection')


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = create_async_engine(
        config.get_main_option("sqlalchemy.url"),
    )
    async with connectable.begin() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    if target_connection is not None:
        # Programmatic call with a pre-existing connection (e.g., from FastAPI lifespan)
        do_run_migrations(target_connection)
    else:
        # Standard standalone mode - create our own engine
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
