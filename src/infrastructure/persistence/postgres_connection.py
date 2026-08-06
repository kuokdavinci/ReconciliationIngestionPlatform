"""PostgreSQL engine and migration bootstrap adapter."""

import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

_pg_engine = None
_pg_engine_loop = None
_pg_engine_url = None


def get_pg_engine():
    global _pg_engine, _pg_engine_loop, _pg_engine_url
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    from src.config.settings import settings

    postgres_url = settings.postgres_url
    if postgres_url.startswith("postgresql://"):
        postgres_url = postgres_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    if (
        _pg_engine is None
        or (current_loop is not None and _pg_engine_loop is not current_loop)
        or _pg_engine_url != postgres_url
    ):
        _pg_engine = create_async_engine(postgres_url, echo=False)
        _pg_engine_loop = current_loop
        _pg_engine_url = postgres_url
    return _pg_engine


def set_pg_engine(engine):
    global _pg_engine, _pg_engine_loop, _pg_engine_url
    _pg_engine = engine
    try:
        _pg_engine_loop = asyncio.get_running_loop()
    except RuntimeError:
        _pg_engine_loop = None
    _pg_engine_url = str(engine.url) if engine is not None else None


async def init_postgres_db(postgres_url: str, use_unlogged: bool = False):
    """Apply all pending Alembic migrations to PostgreSQL."""

    if postgres_url.startswith("postgresql://"):
        postgres_url = postgres_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(postgres_url, echo=False)
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(_run_alembic_upgrade)
        if use_unlogged:
            await conn.execute(text("ALTER TABLE partner_transaction SET UNLOGGED;"))
            await conn.execute(text("ALTER TABLE internal_transaction SET UNLOGGED;"))
    await engine.dispose()


def _run_alembic_upgrade(connection):
    from alembic import command

    cfg = _alembic_config(connection)
    cfg.attributes["connection"] = connection
    command.upgrade(cfg, "head")


def _alembic_config(connection):
    from pathlib import Path
    from alembic.config import Config

    config_path = Path(__file__).resolve().parents[3] / "alembic.ini"
    cfg = Config(str(config_path))
    cfg.set_main_option("sqlalchemy.url", str(connection.engine.url))
    return cfg


__all__ = [
    "get_pg_engine",
    "set_pg_engine",
    "init_postgres_db",
    "_alembic_config",
]
