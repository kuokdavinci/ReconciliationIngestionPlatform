"""Architecture checks for manual reconciliation run state."""

from src.domain.reconciliation.run import ReconciliationRun, ReconciliationRunStatus
from src.infrastructure.reconciliation.run_repository import ReconciliationRunRepository
def test_reconciliation_run_domain_and_adapter_have_separate_ownership() -> None:
    assert ReconciliationRun.__module__ == "src.domain.reconciliation.run"
    assert ReconciliationRunStatus.__module__ == "src.domain.reconciliation.run"
    assert ReconciliationRunRepository.__module__ == "src.infrastructure.reconciliation.run_repository"
