"""Tests for the PostgreSQL-only reconciliation entry point."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.enums import ReconciliationScopeType
from src.infrastructure.reconciliation.composition import build_reconciliation_service
from src.reconciliation.engine import ReconciliationEngine
from src.reconciliation.postgres_executor import PostgresReconciliationExecutor


def _mock_db() -> MagicMock:
    db = MagicMock()
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=None)
    db.__getitem__ = MagicMock(return_value=collection)
    return db


def test_engine_uses_postgres_executor_by_default() -> None:
    engine = ReconciliationEngine(_mock_db())

    assert isinstance(engine._executor, PostgresReconciliationExecutor)


def test_composition_returns_the_postgres_engine() -> None:
    assert isinstance(build_reconciliation_service(_mock_db()), ReconciliationEngine)


@pytest.mark.asyncio
async def test_engine_passes_scope_to_injected_executor() -> None:
    db = _mock_db()
    db["reconciliation_file"].find_one = AsyncMock(
        return_value={"scopeType": ReconciliationScopeType.INCREMENTAL_APPEND.value}
    )
    executor = MagicMock()
    executor.execute = AsyncMock(return_value=[])
    engine = ReconciliationEngine(db, executor=executor)

    result = await engine.reconcile(
        "MOMO",
        datetime(2026, 8, 10, tzinfo=timezone.utc),
        source_file_id="file-1",
        reconciliation_run_id="run-1",
        mapping_version="v1",
    )

    assert result == []
    executor.execute.assert_awaited_once()
    assert executor.execute.call_args.kwargs["partner"] == "MOMO"
    assert executor.execute.call_args.kwargs["date_str"] == "2026-08-10"
    assert executor.execute.call_args.kwargs["scope_type"] is ReconciliationScopeType.INCREMENTAL_APPEND
    assert executor.execute.call_args.kwargs["source_file_id"] == "file-1"


def test_engine_uses_business_timezone_day_bounds() -> None:
    start, end = ReconciliationEngine._business_day_bounds(
        datetime(2026, 8, 10, tzinfo=timezone.utc)
    )

    assert start == datetime(2026, 8, 9, 17, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 10, 16, 59, 59, 999999, tzinfo=timezone.utc)
