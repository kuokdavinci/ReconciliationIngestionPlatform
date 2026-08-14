"""Application services for unified runtime run visibility."""

from datetime import datetime, timezone
from typing import Any, Optional

from src.domain.runtime.models import (
    PartnerRuntimeRun,
    PartnerRuntimeRunStatus,
    PartnerRuntimeTriggerType,
    RuntimeOrchestrationContext,
)
from src.infrastructure.runtime.repository import PartnerRuntimeRunRepository


def serialize_partner_runtime_run(run: PartnerRuntimeRun) -> dict[str, Any]:
    data = run.model_dump(by_alias=True)
    data["_id"] = str(data["_id"])
    for key in ("createdAt", "updatedAt", "startedAt", "finishedAt"):
        value = data.get(key)
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    orchestration_context = getattr(run, "orchestration", None)
    if orchestration_context is not None:
        orchestration = orchestration_context.model_dump(by_alias=True)
        logical_date = orchestration.get("logicalDate")
        if isinstance(logical_date, datetime):
            orchestration["logicalDate"] = logical_date.isoformat()
        data["orchestration"] = orchestration
    return data


async def create_runtime_run(
    db,
    *,
    partner: str,
    date: str,
    trigger_type: PartnerRuntimeTriggerType,
    triggered_by: Optional[str] = None,
    status: PartnerRuntimeRunStatus,
    message: str,
    source_file_id: Optional[str] = None,
    file_name: Optional[str] = None,
    mapping_version: Optional[str] = None,
    validation_state: Optional[str] = None,
    orchestration: RuntimeOrchestrationContext | dict[str, Any] | None = None,
) -> PartnerRuntimeRun:
    repo = PartnerRuntimeRunRepository(db)
    orchestration_context = (
        RuntimeOrchestrationContext.model_validate(orchestration)
        if orchestration is not None
        else None
    )
    run = PartnerRuntimeRun(
        partner=partner,
        date=date,
        triggerType=trigger_type,
        triggeredBy=triggered_by,
        status=status,
        message=message,
        sourceFileId=source_file_id,
        fileName=file_name,
        mappingVersion=mapping_version,
        validationState=validation_state,
        orchestration=orchestration_context,
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
    orchestration: RuntimeOrchestrationContext | dict[str, Any] | None = None,
    stats: Optional[dict[str, Any]] = None,
    reconciliation_count: Optional[int] = None,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
    clear_finished_at: bool = False,
    attempt_event: Optional[dict[str, Any]] = None,
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
    if orchestration is not None:
        context = RuntimeOrchestrationContext.model_validate(orchestration)
        update["orchestration"] = context.model_dump(by_alias=True, mode="json")
    if stats is not None:
        update["stats"] = stats
    if reconciliation_count is not None:
        update["reconciliationCount"] = reconciliation_count
    if started_at is not None:
        update["startedAt"] = started_at
    if finished_at is not None:
        update["finishedAt"] = finished_at
    elif clear_finished_at:
        update["finishedAt"] = None
    await PartnerRuntimeRunRepository(db).update_fields(
        run_id,
        update,
        attempt_event=attempt_event,
    )
