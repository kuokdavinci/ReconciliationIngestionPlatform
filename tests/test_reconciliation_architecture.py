from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.reconciliation.service import ReconciliationCommand, ReconciliationService
from src.reconciliation.document_executor import DocumentReconciliationExecutor
from src.reconciliation.engine import ReconciliationEngine


@pytest.mark.asyncio
async def test_reconciliation_service_dispatches_command_to_runner():
    runner = MagicMock()
    runner.reconcile = AsyncMock(return_value=["result"])
    reconciliation_date = datetime(2026, 8, 5, tzinfo=UTC)
    service = ReconciliationService(runner)

    result = await service.execute(
        ReconciliationCommand(
            partner="MOMO",
            reconciliation_date=reconciliation_date,
            source_file_id="file-1",
            reconciliation_run_id="run-1",
            mapping_version="v1",
        )
    )

    assert result == ["result"]
    runner.reconcile.assert_awaited_once_with(
        "MOMO",
        reconciliation_date,
        source_file_id="file-1",
        reconciliation_run_id="run-1",
        mapping_version="v1",
    )


def test_reconciliation_engine_accepts_injected_repository_ports():
    db = MagicMock()
    data_repo = MagicMock()
    internal_repo = MagicMock()
    result_repo = MagicMock()

    engine = ReconciliationEngine(
        db,
        data_repo=data_repo,
        internal_repo=internal_repo,
        result_repo=result_repo,
        backend="document",
    )

    assert engine._data_repo is data_repo
    assert engine._internal_repo is internal_repo
    assert engine._result_repo is result_repo
    assert isinstance(engine._executor, DocumentReconciliationExecutor)
