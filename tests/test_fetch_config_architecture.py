"""Architecture checks for the fetch configuration bounded context."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.fetch_config.models import (
    APIConfig,
    APIPaginationConfig,
    FetchConfig,
    FetchMethod,
    FileDropConfig,
    SFTPConfig,
)
from src.infrastructure.fetch_config.repository import FetchConfigRepository
from src.models.fetch_config import (
    APIConfig as LegacyAPIConfig,
    APIPaginationConfig as LegacyAPIPaginationConfig,
    FetchConfig as LegacyFetchConfig,
    FetchConfigRepository as LegacyFetchConfigRepository,
    FetchMethod as LegacyFetchMethod,
    FileDropConfig as LegacyFileDropConfig,
    SFTPConfig as LegacySFTPConfig,
)


def test_legacy_fetch_config_module_is_a_compatibility_facade() -> None:
    """Legacy imports must resolve to domain and infrastructure implementations."""

    assert LegacyAPIConfig is APIConfig
    assert LegacyAPIPaginationConfig is APIPaginationConfig
    assert LegacyFetchConfig is FetchConfig
    assert LegacyFetchConfigRepository is FetchConfigRepository
    assert LegacyFetchMethod is FetchMethod
    assert LegacyFileDropConfig is FileDropConfig
    assert LegacySFTPConfig is SFTPConfig


@pytest.mark.asyncio
async def test_fetch_config_repository_finds_config_by_string_id() -> None:
    config = FetchConfig(
        partner="VIETTELPAY",
        fetchMethod=FetchMethod.API,
        api=APIConfig(baseUrl="https://partner.example/settlement"),
    )
    collection = MagicMock()
    collection.find_one = AsyncMock(
        return_value=config.model_dump(by_alias=True, exclude_none=False)
    )
    db = MagicMock()
    db.__getitem__.return_value = collection

    result = await FetchConfigRepository(db).find_by_id(str(config.id))

    collection.find_one.assert_awaited_once_with({"_id": str(config.id)})
    assert result == config
