"""Ports used by the reconciliation use case.

The concrete Motor/PostgreSQL repositories remain in the existing model modules
for now.  These protocols make the dependency direction explicit while allowing
the migration to happen incrementally without changing the reconciliation
algorithm's public API.
"""

from datetime import datetime
from typing import Any, Protocol

from src.core.enums import ReconciliationScopeType


class PartnerTransactionReader(Protocol):
    """Read canonical partner transactions for reconciliation."""

    async def find_many(self, query: dict[str, Any]) -> list[Any]:
        """Return partner transactions matching the query."""


class InternalTransactionReader(Protocol):
    """Read finalized internal transactions for reconciliation."""

    async def find_by_partner_and_date_range(
        self,
        partner: str,
        start: datetime,
        end: datetime,
    ) -> list[Any]:
        """Return internal transactions in a partner/date scope."""


class ReconciliationResultWriter(Protocol):
    """Persist reconciliation results and clear the active scope."""

    async def delete_by_partner_and_date(
        self,
        partner: str,
        date: str,
        **kwargs: Any,
    ) -> Any:
        """Delete results that belong to the active reconciliation scope."""

    async def insert_many(self, documents: list[Any], ordered: bool = True) -> int:
        """Persist a batch of reconciliation results."""


class ReconciliationExecutor(Protocol):
    """Execute one reconciliation scope against an explicit storage backend."""

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
    ) -> list[Any]:
        """Execute reconciliation for the supplied business-day scope."""


class ReconciliationRunner(Protocol):
    """Application-facing reconciliation operation."""

    async def reconcile(
        self,
        partner: str,
        reconciliation_date: datetime,
        *,
        source_file_id: str | None = None,
        reconciliation_run_id: str | None = None,
        mapping_version: str | None = None,
    ) -> list[Any]:
        """Reconcile one partner/date scope."""
