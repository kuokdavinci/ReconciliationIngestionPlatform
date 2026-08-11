"""Pure helpers used by the Airflow DAG adapter."""

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.application.automation.contracts import ExecuteStreamCommand

BUSINESS_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def resolve_schedule(value: str) -> str | None:
    schedule = value.strip()
    if schedule.lower() in {"", "none", "null"}:
        return None
    return schedule


def business_date(interval_end: datetime) -> date:
    return interval_end.astimezone(BUSINESS_TIMEZONE).date()


def resolve_reconciliation_date(
    conf: dict[str, Any],
    interval_end: datetime | None,
) -> date:
    configured_date = conf.get("reconciliationDate")
    if configured_date is not None:
        return date.fromisoformat(str(configured_date))
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
