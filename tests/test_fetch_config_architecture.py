"""Architecture checks for the fetch configuration bounded context."""

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
