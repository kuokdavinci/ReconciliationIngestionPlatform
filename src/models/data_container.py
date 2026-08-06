"""Compatibility exports for the partner transaction bounded context.

New production code should import models from ``src.domain.partner_transaction``
and the PostgreSQL adapter from ``src.infrastructure.partner_transaction``.
"""

from src.core.types import BatchInsertResult
from src.domain.partner_transaction.models import DataContainer, PartnerData
from src.infrastructure.partner_transaction.repository import (
    DataContainerRepository,
    data_container_to_row,
    row_to_data_container,
)

__all__ = [
    "BatchInsertResult",
    "DataContainer",
    "DataContainerRepository",
    "PartnerData",
    "data_container_to_row",
    "row_to_data_container",
]
