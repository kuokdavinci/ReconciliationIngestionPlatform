"""Composition root for the reconciliation use case."""

from collections.abc import Callable
from typing import Any

from src.application.reconciliation.service import ReconciliationService
from src.infrastructure.partner_transaction.repository import DataContainerRepository
from src.infrastructure.postgres.internal_transaction_repository import InternalTransactionRepository
from src.infrastructure.postgres.reconciliation_result_repository import ReconciliationResultRepository
from src.domain.reconciliation.ports import ReconciliationRunner
from src.reconciliation.engine import ReconciliationEngine


def build_reconciliation_service(
    db: Any,
    *,
    fast_mode: bool = False,
    engine_factory: Callable[..., ReconciliationRunner] | None = None,
) -> ReconciliationService:
    """Build the reconciliation use case with production adapters.

    Concrete repository imports intentionally live here.  API/application code
    can therefore depend on the use case and ports without knowing whether a
    repository is backed by PostgreSQL, MongoDB metadata, or a test double.
    """

    runner_builder = engine_factory or ReconciliationEngine
    runner = runner_builder(
        db,
        fast_mode=fast_mode,
        data_repo=DataContainerRepository(db),
        internal_repo=InternalTransactionRepository(db),
        result_repo=ReconciliationResultRepository(db),
    )
    return ReconciliationService(runner)
