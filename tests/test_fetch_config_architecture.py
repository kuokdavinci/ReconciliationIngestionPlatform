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
def test_fetch_config_domain_and_adapter_have_separate_ownership() -> None:
    assert APIConfig.__module__ == "src.domain.fetch_config.models"
    assert APIPaginationConfig.__module__ == "src.domain.fetch_config.models"
    assert FetchConfig.__module__ == "src.domain.fetch_config.models"
    assert FetchConfigRepository.__module__ == "src.infrastructure.fetch_config.repository"
    assert FetchMethod.__module__ == "src.domain.fetch_config.models"
    assert FileDropConfig.__module__ == "src.domain.fetch_config.models"
    assert SFTPConfig.__module__ == "src.domain.fetch_config.models"


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
