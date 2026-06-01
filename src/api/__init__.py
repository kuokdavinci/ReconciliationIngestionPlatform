"""FastAPI application factory for the AI Analysis Layer.

Provides create_app() function that initializes the FastAPI app
with MongoDB connection management via lifespan context manager
and registers the insights router.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient

from src.analysis.config import AnalysisConfig
from src.analysis.provider import create_provider
from src.config.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage MongoDB connection lifecycle.

    Creates client on startup, closes on shutdown.
    """
    # Startup: create MongoDB client and attach to app state
    client = AsyncIOMotorClient(settings.mongodb_url)
    app.state.db = client[settings.db_name]
    app.state.mongo_client = client

    # Apply indexes on startup
    from src.models.indexes import apply_indexes

    await apply_indexes(app.state.db)

    yield

    # Shutdown: close MongoDB client
    client.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Initializes:
    - Lifespan management for MongoDB connection
    - Analysis config and LLM provider
    - Insights router with dependencies

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(
        title="Reconciliation AI Analysis API",
        description="AI-powered reconciliation insight engine",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Register insights router
    from src.api.insights import router as insights_router

    app.include_router(insights_router)

    return app
