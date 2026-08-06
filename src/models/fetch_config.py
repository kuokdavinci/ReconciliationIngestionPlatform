"""Compatibility facade for fetch configuration models and repository."""

from src.domain.fetch_config.models import (
    APIConfig,
    APIPaginationConfig,
    FetchConfig,
    FetchMethod,
    FileDropConfig,
    SFTPConfig,
)
from src.infrastructure.fetch_config.repository import FetchConfigRepository

__all__ = [
    "APIConfig",
    "APIPaginationConfig",
    "FetchConfig",
    "FetchConfigRepository",
    "FetchMethod",
    "FileDropConfig",
    "SFTPConfig",
]
