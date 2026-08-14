from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from src.application.automation.airflow_runtime import (
    business_date,
    resolve_reconciliation_date,
    resolve_schedule,
    select_stream_commands,
)
from src.domain.fetch_config.models import APIConfig, FetchConfig, FetchMethod


def _config(partner: str, config_id: str) -> FetchConfig:
    return FetchConfig(
        _id=UUID(config_id),
        partner=partner,
        fetchMethod=FetchMethod.API,
        api=APIConfig(
            baseUrl="https://partner.example/settlement",
            headers={"Authorization": "secret-token"},
        ),
        updatedAt=datetime(2026, 8, 9, 1, 2, 3, tzinfo=UTC),
    )


def test_business_date_uses_ho_chi_minh_timezone() -> None:
    interval_end = datetime(2026, 8, 8, 17, 0, tzinfo=UTC)

    assert business_date(interval_end).isoformat() == "2026-08-09"


def test_business_date_uses_configured_core_timezone(monkeypatch) -> None:
    from src.config.settings import settings

    monkeypatch.setattr(settings, "business_timezone", "UTC")

    assert business_date(datetime(2026, 8, 8, 17, 0, tzinfo=UTC)) == date(2026, 8, 8)


def test_airflow_schedule_can_be_disabled_for_manual_only_pilot() -> None:
    assert resolve_schedule("none") is None
    assert resolve_schedule("  NULL  ") is None
    assert resolve_schedule("0 0 * * *") == "0 0 * * *"


def test_airflow_is_the_default_application_orchestrator() -> None:
    from src.config.settings import Settings

    assert Settings(_env_file=None).automation_orchestrator == "airflow"


def test_manual_run_uses_reconciliation_date_without_data_interval() -> None:
    assert resolve_reconciliation_date(
        {"reconciliationDate": "2026-08-09"},
        None,
    ) == date(2026, 8, 9)


def test_manual_backfill_uses_from_date_without_data_interval() -> None:
    assert resolve_reconciliation_date(
        {
            "mode": "BACKFILL",
            "fromDate": "2026-08-10",
            "toDate": "2026-08-12",
        },
        None,
    ) == date(2026, 8, 10)


@pytest.mark.asyncio
async def test_scheduled_selection_is_stable_and_does_not_expose_config_secrets() -> None:
    repository = MagicMock()
    repository.find_enabled = AsyncMock(
        return_value=[
            _config("VIETTELPAY", "00000000-0000-0000-0000-000000000002"),
            _config("MOMO", "00000000-0000-0000-0000-000000000001"),
        ]
    )

    commands = await select_stream_commands(
        conf={},
        reconciliation_date=business_date(datetime(2026, 8, 8, 17, 0, tzinfo=UTC)),
        dag_run_id="scheduled__2026-08-09",
        repository=repository,
    )

    assert [command["partner"] for command in commands] == ["MOMO", "VIETTELPAY"]
    assert all(command["reconciliationDate"] == "2026-08-09" for command in commands)
    assert all(command["mode"] == "SCHEDULED" for command in commands)
    assert "secret-token" not in str(commands)


@pytest.mark.asyncio
async def test_manual_selection_preserves_runtime_and_backfill_scope() -> None:
    repository = MagicMock()
    command = {
        "schemaVersion": 1,
        "fetchConfigId": "config-1",
        "partner": "VIETTELPAY",
        "configVersion": "version-1",
        "reconciliationDate": "2026-08-01",
        "mode": "BACKFILL",
        "runtimeRunId": "runtime-1",
        "correlationId": "runtime:runtime-1",
        "backfillRunId": "backfill-1",
        "fromDate": "2026-08-01",
        "toDate": "2026-08-31",
    }

    commands = await select_stream_commands(
        conf=command,
        reconciliation_date=business_date(datetime(2026, 8, 8, 17, 0, tzinfo=UTC)),
        dag_run_id="manual__runtime-1",
        repository=repository,
    )

    assert commands == [command]
    repository.find_enabled.assert_not_called()
