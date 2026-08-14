from unittest.mock import MagicMock

from src.domain.internal_transaction.models import InternalTransaction
from src.domain.reconciliation.models import ReconciliationResult
from src.infrastructure.postgres.internal_transaction_repository import InternalTransactionRepository
from src.infrastructure.postgres.reconciliation_result_repository import ReconciliationResultRepository
def test_transaction_models_and_repositories_have_separate_ownership():
    assert InternalTransaction.__module__ == "src.domain.internal_transaction.models"
    assert InternalTransactionRepository.__module__ == "src.infrastructure.postgres.internal_transaction_repository"
    assert ReconciliationResult.__module__ == "src.domain.reconciliation.models"
    assert ReconciliationResultRepository.__module__ == "src.infrastructure.postgres.reconciliation_result_repository"


def test_transaction_repositories_accept_explicit_postgres_engines():
    engine = MagicMock()

    assert InternalTransactionRepository(engine=engine).engine is engine
    assert ReconciliationResultRepository(engine=engine).engine is engine
