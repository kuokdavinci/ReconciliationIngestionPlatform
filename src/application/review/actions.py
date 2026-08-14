"""Review packet state changes and approval actions."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from src.application.automation.backfill_service import (
    BackfillRunService,
    serialize_backfill_run,
)
from src.application.audit.service import record_audit_event
from src.application.review.errors import (
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewUnavailableError,
)
from src.application.review.reprocessing import (
    ScheduleBackground,
    queue_post_approval_reprocess,
)
from src.config.settings import settings
from src.core.business_day import business_date
from src.domain.mapping.models import MappingConfigStatus
from src.domain.review.models import (
    CopilotActionStatus,
    ReviewDecisionMode,
    ReviewPacketStatus,
)
from src.infrastructure.backfill.repository import BackfillRunRepository
from src.infrastructure.fetch_config.repository import FetchConfigRepository
from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.infrastructure.review.repository import (
    CopilotActionRepository,
    ReviewPacketRepository,
)
from src.infrastructure.workflows.airflow import AirflowWorkflowGateway


async def sync_action_status(db, action_id: Optional[str], status: str) -> None:
    if not action_id:
        return
    repo = CopilotActionRepository(db)
    update = {"status": status, "reviewedAt": datetime.now(timezone.utc)}
    await repo.collection.update_one({"_id": action_id}, {"$set": update})


async def mark_packet(
    db,
    packet_id: str,
    status: ReviewPacketStatus,
    decision_mode: ReviewDecisionMode,
    reviewed_by: Optional[str],
    serializer,
):
    repo = ReviewPacketRepository(db)
    packet = await repo.find_one({"_id": packet_id})
    if packet is None:
        raise ReviewNotFoundError("Review packet not found.")
    if packet.status != ReviewPacketStatus.PENDING:
        raise ReviewConflictError("Only pending review packets can be processed.")

    now = datetime.now(timezone.utc)
    set_fields: dict[str, Any] = {
        "status": status.value,
        "decisionMode": decision_mode.value,
        "reviewedAt": now,
        "reviewedBy": reviewed_by,
    }
    if status == ReviewPacketStatus.APPROVED:
        gates = [dict(g) for g in (packet.validation_gates or [])]
        for gate in gates:
            gate["status"] = "pass"
        set_fields["validationGates"] = gates
    await repo.collection.update_one(
        {"_id": packet_id},
        {"$set": set_fields},
    )
    await sync_action_status(
        db,
        packet.target_action_id,
        CopilotActionStatus.APPROVED.value
        if status == ReviewPacketStatus.APPROVED
        else CopilotActionStatus.REJECTED.value,
    )
    packet.status = status
    packet.decision_mode = decision_mode
    packet.reviewed_at = now
    packet.reviewed_by = reviewed_by
    reconciliation_date = getattr(packet, "reconciliation_date", None)
    audit_date = (
        business_date(reconciliation_date).isoformat()
        if isinstance(reconciliation_date, datetime)
        else None
    )
    await record_audit_event(
        db,
        entity_type="REVIEW_PACKET",
        entity_id=packet_id,
        action=decision_mode.value,
        actor=reviewed_by,
        metadata={
            "partner": packet.partner,
            "date": audit_date,
            "status": status.value,
            "reference": packet.draft_mapping_version
            or packet.draft_mapping_id
            or packet.source_file_id,
            "draftMappingId": packet.draft_mapping_id,
            "draftMappingVersion": packet.draft_mapping_version,
            "sourceFileId": packet.source_file_id,
        },
    )
    return {"ok": True, "packet": serializer(packet)}


async def update_packet_scope(
    db,
    packet_id: str,
    packet,
    scope_type: Optional[str],
) -> None:
    if not scope_type:
        return
    repo = ReviewPacketRepository(db)
    packet.scope_type = scope_type
    await repo.collection.update_one(
        {"_id": packet_id},
        {"$set": {"scopeType": scope_type}},
    )
    if packet.source_file_id:
        file_repo = ReconciliationFileRepository(db)
        await file_repo.update_one(
            {"_id": packet.source_file_id},
            {"scopeType": scope_type},
        )


async def approve_packet_mapping_and_reprocess(
    db,
    packet,
    reviewed_by: Optional[str],
    *,
    schedule_background: ScheduleBackground,
    workflow_gateway: Any | None = None,
) -> dict | None:
    if not packet.draft_mapping_id:
        return None

    mapping_repo = MappingConfigRepository(db)
    config = await mapping_repo.find_one({"_id": packet.draft_mapping_id})
    if config is None:
        return None

    if config.status == MappingConfigStatus.PENDING_APPROVAL:
        now = datetime.now(timezone.utc)
        current_approved = await mapping_repo.find_by_partner_and_type(
            config.partner, config.workflow_type, config.file_type
        )
        if current_approved is not None:
            await mapping_repo.collection.update_one(
                {"_id": str(current_approved.id)},
                {
                    "$set": {
                        "status": MappingConfigStatus.SUPERSEDED.value,
                        "supersededAt": now,
                        "supersededByConfigId": str(config.id),
                    }
                },
            )
        health = dict(config.config_health or {})
        health.update(
            {
                "stale": False,
                "status": MappingConfigStatus.APPROVED.value,
                "approvedAt": now,
                "reasoning": health.get("reasoning")
                or "Approved from review packet.",
            }
        )
        await mapping_repo.collection.update_one(
            {"_id": packet.draft_mapping_id},
            {
                "$set": {
                    "status": MappingConfigStatus.APPROVED.value,
                    "approvedAt": now,
                    "approvedBy": reviewed_by,
                    "configHealth": health,
                }
            },
        )
        config.status = MappingConfigStatus.APPROVED
        config.approved_at = now
        config.approved_by = reviewed_by
        config.config_health = health
    elif config.status != MappingConfigStatus.APPROVED:
        return None

    if getattr(packet, "backfill_run_id", None):
        gateway = workflow_gateway
        if gateway is None:
            if settings.automation_orchestrator != "airflow":
                raise ReviewUnavailableError(
                    "Backfill approval requires the Airflow orchestrator."
                )
            if not settings.airflow_username or not settings.airflow_password:
                raise ReviewUnavailableError(
                    "Airflow credentials are required for backfill approval."
                )
            gateway = AirflowWorkflowGateway(
                base_url=settings.airflow_base_url,
                dag_id=settings.airflow_dag_id,
                username=settings.airflow_username,
                password=settings.airflow_password,
                timeout_seconds=settings.airflow_request_timeout_seconds,
            )
        service = BackfillRunService(
            fetch_repo=FetchConfigRepository(db),
            backfill_repo=BackfillRunRepository(db),
            workflow_gateway=gateway,
            approved_mapping_version_finder=lambda _partner: asyncio.sleep(
                0, result=config.config_version
            ),
        )
        backfill_run = await service.resume_after_approval(
            backfill_run_id=str(packet.backfill_run_id),
            mapping_version=str(config.config_version or ""),
        )
        return {"backfillRun": serialize_backfill_run(backfill_run)}

    return await queue_post_approval_reprocess(
        db,
        packet,
        config,
        schedule_background=schedule_background,
    )


async def reprocess_packet_with_current_mapping(
    db,
    packet,
    reviewed_by: Optional[str],
    *,
    schedule_background: ScheduleBackground,
) -> dict | None:
    """Queue replay for a scope-approved stream with its active mapping."""
    config_id = getattr(packet, "active_runtime_config_id", None)
    if not config_id:
        return None
    config = await MappingConfigRepository(db).find_one({"_id": config_id})
    if config is None or config.status != MappingConfigStatus.APPROVED:
        return None
    return await queue_post_approval_reprocess(
        db,
        packet,
        config,
        schedule_background=schedule_background,
    )
