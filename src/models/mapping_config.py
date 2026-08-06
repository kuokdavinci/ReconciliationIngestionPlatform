"""Compatibility exports for the mapping bounded context.

New production code should import models from ``src.domain.mapping`` and the
repository from ``src.infrastructure.mapping``.
"""

from src.domain.mapping.models import MappingConfig, MappingConfigStatus
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.core.enums import FileType

__all__ = [
    "FileType",
    "MappingConfig",
    "MappingConfigStatus",
    "MappingConfigRepository",
]
