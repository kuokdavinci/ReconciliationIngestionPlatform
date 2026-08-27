"""Ports used by the reconciliation use case.

The concrete Motor/PostgreSQL repositories remain in the existing model modules
for now.  These protocols make the dependency direction explicit while allowing
the migration to happen incrementally without changing the reconciliation
algorithm's public API.
"""

from datetime import datetime
from typing import Protocol, TypeAlias

from src.core.enums import ReconciliationScopeType
from src.domain.reconciliation.models import ReconciliationResult


ReconciliationOutput: TypeAlias = ReconciliationResult


class ReconciliationExecutor(Protocol):
    """Execute one reconciliation scope against PostgreSQL."""

    async def execute(
        self,
        *,
        partner: str,
        start_of_day: datetime,
        end_of_day: datetime,
        date_str: str,
        scope_type: ReconciliationScopeType,
        source_file_id: str | None = None,
        reconciliation_run_id: str | None = None,
        mapping_version: str | None = None,
        started_at: float | None = None,
    ) -> list[ReconciliationOutput]:
        """Execute reconciliation for the supplied business-day scope."""
