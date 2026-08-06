"""Compatibility exports for the internal transaction bounded context."""

from src.domain.internal_transaction.models import InternalTransaction
from src.infrastructure.postgres.internal_transaction_repository import (
    InternalTransactionRepository,
    internal_transaction_to_row,
    row_to_internal_transaction,
)

__all__ = [
    "InternalTransaction",
    "InternalTransactionRepository",
    "internal_transaction_to_row",
    "row_to_internal_transaction",
]
