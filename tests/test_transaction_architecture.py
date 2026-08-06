from unittest.mock import MagicMock

from src.domain.internal_transaction.models import InternalTransaction
from src.domain.reconciliation.models import ReconciliationResult
from src.infrastructure.postgres.internal_transaction_repository import InternalTransactionRepository
from src.infrastructure.postgres.reconciliation_result_repository import ReconciliationResultRepository
from src.models.internal_transaction import (
    InternalTransaction as LegacyInternalTransaction,
    InternalTransactionRepository as LegacyInternalRepository,
)
from src.models.reconciliation_result import (
    ReconciliationResult as LegacyReconciliationResult,
    ReconciliationResultRepository as LegacyResultRepository,
)


def test_transaction_models_and_repositories_keep_legacy_identity():
    assert LegacyInternalTransaction is InternalTransaction
    assert LegacyInternalRepository is InternalTransactionRepository
    assert LegacyReconciliationResult is ReconciliationResult
    assert LegacyResultRepository is ReconciliationResultRepository


def test_transaction_repositories_accept_explicit_postgres_engines():
    engine = MagicMock()

    assert InternalTransactionRepository(engine=engine).engine is engine
    assert ReconciliationResultRepository(engine=engine).engine is engine
