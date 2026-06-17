"""Helpers for unified runtime run visibility."""

from datetime import datetime, timezone
from typing import Any, Optional

from src.models.partner_runtime_run import (
    PartnerRuntimeRun,
    PartnerRuntimeRunRepository,
    PartnerRuntimeRunStatus,
    PartnerRuntimeTriggerType,
)


def serialize_partner_runtime_run(run: PartnerRuntimeRun) -> dict[str, Any]:
    data = run.model_dump(by_alias=True)
    data["_id"] = str(data["_id"])
    for key in ("createdAt", "updatedAt", "startedAt", "finishedAt"):
        value = data.get(key)
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return data


async def create_runtime_run(
    db,
    *,
    partner: str,
    date: str,
    trigger_type: PartnerRuntimeTriggerType,
    status: PartnerRuntimeRunStatus,
    message: str,
    source_file_id: Optional[str] = None,
    file_name: Optional[str] = None,
    mapping_version: Optional[str] = None,
    validation_state: Optional[str] = None,
) -> PartnerRuntimeRun:
    repo = PartnerRuntimeRunRepository(db)
    run = PartnerRuntimeRun(
        partner=partner,
        date=date,
        triggerType=trigger_type,
        status=status,
        message=message,
        sourceFileId=source_file_id,
        fileName=file_name,
        mappingVersion=mapping_version,
        validationState=validation_state,
    )
    await repo.create(run)
    return run


async def update_runtime_run(
    db,
    run_id: str,
    *,
    status: Optional[PartnerRuntimeRunStatus] = None,
    message: Optional[str] = None,
    source_file_id: Optional[str] = None,
    file_name: Optional[str] = None,
    mapping_version: Optional[str] = None,
    validation_state: Optional[str] = None,
    stats: Optional[dict[str, Any]] = None,
    reconciliation_count: Optional[int] = None,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
) -> None:
    update: dict[str, Any] = {"updatedAt": datetime.now(timezone.utc)}
    if status is not None:
        update["status"] = status.value
    if message is not None:
        update["message"] = message
    if source_file_id is not None:
        update["sourceFileId"] = source_file_id
    if file_name is not None:
        update["fileName"] = file_name
    if mapping_version is not None:
        update["mappingVersion"] = mapping_version
    if validation_state is not None:
        update["validationState"] = validation_state
    if stats is not None:
        update["stats"] = stats
    if reconciliation_count is not None:
        update["reconciliationCount"] = reconciliation_count
    if started_at is not None:
        update["startedAt"] = started_at
    if finished_at is not None:
        update["finishedAt"] = finished_at
    await PartnerRuntimeRunRepository(db).collection.update_one({"_id": run_id}, {"$set": update})
