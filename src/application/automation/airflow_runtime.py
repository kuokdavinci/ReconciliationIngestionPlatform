"""Pure helpers used by the Airflow DAG adapter."""

from datetime import date, datetime
from typing import Any

from src.application.automation.contracts import ExecuteStreamCommand
from src.core.business_day import business_date


def resolve_schedule(value: str) -> str | None:
    schedule = value.strip()
    if schedule.lower() in {"", "none", "null"}:
        return None
    return schedule


def resolve_reconciliation_date(
    conf: dict[str, Any],
    interval_end: datetime | None,
) -> date:
    configured_date = conf.get("reconciliationDate")
    if configured_date is not None:
        return date.fromisoformat(str(configured_date))
    # Manual backfill DAG runs do not have Airflow's data interval.  The
    # backfill command already carries its deterministic lower boundary, so
    # use it instead of treating a missing interval as a scheduler failure.
    backfill_from = conf.get("fromDate")
    if str(conf.get("mode", "")).upper() == "BACKFILL" and backfill_from is not None:
        return date.fromisoformat(str(backfill_from))
    if interval_end is None:
        raise ValueError("Scheduled DAG run requires data_interval_end")
    return business_date(interval_end)


async def select_stream_commands(
    *,
    conf: dict[str, Any],
    reconciliation_date: date,
    dag_run_id: str,
    repository: Any,
) -> list[dict[str, Any]]:
    if conf.get("fetchConfigId"):
        command = ExecuteStreamCommand.model_validate(conf)
        return [command.model_dump(by_alias=True, mode="json", exclude_none=True)]

    configs = sorted(await repository.find_enabled(), key=lambda item: str(item.id))
    commands = [
        ExecuteStreamCommand(
            fetchConfigId=str(config.id),
            partner=config.partner,
            configVersion=str(config.updated_at),
            reconciliationDate=reconciliation_date,
            correlationId=f"airflow:{dag_run_id}:{config.id}",
        )
        for config in configs
    ]
    return [
        command.model_dump(by_alias=True, mode="json", exclude_none=True)
        for command in commands
    ]
