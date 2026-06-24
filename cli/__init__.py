"""Shared CLI utilities."""

from motor.motor_asyncio import AsyncIOMotorClient
from src.config.settings import settings


async def get_db():
    """Create MongoDB connection and return database handle."""
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.db_name]
    return db, client


async def init_databases(db):
    """Apply MongoDB indexes and initialize PostgreSQL tables."""
    from src.models.indexes import apply_indexes
    from src.models.postgres import init_postgres_db
    await apply_indexes(db)
    await init_postgres_db(settings.postgres_url)
