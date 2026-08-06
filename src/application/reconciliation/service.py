"""Reconciliation use case orchestration."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.domain.reconciliation.ports import ReconciliationRunner


@dataclass(frozen=True)
class ReconciliationCommand:
    """Input required to execute one reconciliation scope."""

    partner: str
    reconciliation_date: datetime
    source_file_id: str | None = None
    reconciliation_run_id: str | None = None
    mapping_version: str | None = None


class ReconciliationService:
    """Execute reconciliation through an injected domain port."""

    def __init__(self, runner: ReconciliationRunner) -> None:
        self._runner = runner

    async def execute(self, command: ReconciliationCommand) -> list[Any]:
        """Dispatch a validated command to the reconciliation runner."""

        return await self._runner.reconcile(
            command.partner,
            command.reconciliation_date,
            source_file_id=command.source_file_id,
            reconciliation_run_id=command.reconciliation_run_id,
            mapping_version=command.mapping_version,
        )
