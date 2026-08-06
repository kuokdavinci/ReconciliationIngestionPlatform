"""Architecture checks for manual reconciliation run state."""

from src.domain.reconciliation.run import ReconciliationRun, ReconciliationRunStatus
from src.infrastructure.reconciliation.run_repository import ReconciliationRunRepository
from src.models.reconciliation_run import (
    ReconciliationRun as LegacyReconciliationRun,
    ReconciliationRunRepository as LegacyReconciliationRunRepository,
    ReconciliationRunStatus as LegacyReconciliationRunStatus,
)


def test_legacy_reconciliation_run_module_is_a_compatibility_facade() -> None:
    """Legacy imports must resolve to domain and infrastructure implementations."""

    assert LegacyReconciliationRun is ReconciliationRun
    assert LegacyReconciliationRunRepository is ReconciliationRunRepository
    assert LegacyReconciliationRunStatus is ReconciliationRunStatus
