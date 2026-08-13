"""Composition helpers for mapping configuration adapters."""

from typing import Any

from src.config.cache import ConfigCache
from src.config.loader import ConfigLoader
from src.config.validator import ConfigValidator
from src.infrastructure.mapping.config_repository import MappingConfigRepository


def build_config_loader(db: Any) -> ConfigLoader:
    """Build the production mapping loader for an application use case."""

    return ConfigLoader(
        MappingConfigRepository(db),
        ConfigCache(),
        ConfigValidator(),
    )
