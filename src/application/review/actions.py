"""Shared review packet approval and reprocessing actions."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from src.analysis.insights import invalidate_insight_cache
from src.core.error_formatting import summarize_runtime_error
from src.core.enums import ProcessingStatus, ReconciliationScopeType
from src.domain.review.models import CopilotActionStatus
from src.infrastructure.review.repository import CopilotActionRepository
from src.domain.mapping.models import MappingConfigStatus
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.domain.review.models import (
    PostApprovalRun,
    PostApprovalRunStage,
    PostApprovalRunStatus,
)
from src.infrastructure.review.repository import PostApprovalRunRepository
from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository
from src.infrastructure.ingestion.raw_page_repository import RawIngestionPageRepository
from src.infrastructure.partner_transaction.repository import DataContainerRepository
from src.infrastructure.postgres.reconciliation_result_repository import ReconciliationResultRepository
from src.domain.review.models import (
    ReviewDecisionMode,
    ReviewPacketStatus,
)
from src.infrastructure.review.repository import ReviewPacketRepository
from src.infrastructure.ingestion.composition import build_ingestion_pipeline
from src.infrastructure.fetch_config.repository import FetchConfigRepository
from src.infrastructure.backfill.repository import BackfillRunRepository
from src.infrastructure.workflows.airflow import AirflowWorkflowGateway
from src.application.reconciliation.service import ReconciliationCommand
from src.infrastructure.reconciliation.composition import build_reconciliation_service
from src.application.audit.service import record_audit_event
from src.application.runtime.service import create_runtime_run, update_runtime_run
from src.core.business_day import business_date
from src.application.review.raw_stream import resolve_review_source_file
from src.application.review.errors import (
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewUnavailableError,
)
from src.infrastructure.mapping.composition import build_config_loader
from src.domain.runtime.models import PartnerRuntimeRunStatus, PartnerRuntimeTriggerType
from src.config.settings import settings
from src.application.automation.backfill_service import BackfillRunService, serialize_backfill_run


async def _rebind_replacement_transactions(
    *,
    db,
    packet,
    config,
    ingestion_result,
    source_file_id: str,
) -> int:
    """Attach deduplicated replacement rows to the current logical file.

    The ingestion key is intentionally unique across deliveries, so rows that
    overlap a replacement file are reported as duplicates and remain stored
    under the prior source file. Reconciliation scopes partner rows by the
    current source file; rebind every valid key from the replacement payload so
    the complete replacement dataset is visible to the reconciliation engine.
    """
    scope_type = getattr(packet, "scope_type", None)
    scope_type = getattr(scope_type, "value", scope_type)
    if scope_type != ReconciliationScopeType.REPLACEMENT.value:
        return 0

    keys = list(dict.fromkeys(
        str(key).strip()
        for key in (getattr(ingestion_result, "ingestion_keys", None) or [])
        if str(key).strip()
    ))
    if not keys:
        return 0
    return await DataContainerRepository(db).rebind_source_file_by_ingestion_keys(
        config.partner,
        keys,
        source_file_id,
    )


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
        for g in gates:
            g["status"] = "pass"
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
    audit_date = (
        business_date(packet.reconciliation_date).isoformat()
        if getattr(packet, "reconciliation_date", None)
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
            "reference": packet.draft_mapping_version or packet.draft_mapping_id or packet.source_file_id,
            "draftMappingId": packet.draft_mapping_id,
            "draftMappingVersion": packet.draft_mapping_version,
            "sourceFileId": packet.source_file_id,
        },
    )
    return {"ok": True, "packet": serializer(packet)}


async def update_packet_scope(db, packet_id: str, packet, scope_type: Optional[str]) -> None:
    if not scope_type:
        return
    repo = ReviewPacketRepository(db)
    packet.scope_type = scope_type
    await repo.collection.update_one({"_id": packet_id}, {"$set": {"scopeType": scope_type}})
    if packet.source_file_id:
        file_repo = ReconciliationFileRepository(db)
        await file_repo.update_one({"_id": packet.source_file_id}, {"scopeType": scope_type})


def serialize_post_approval_run(run: PostApprovalRun) -> dict[str, Any]:
    data = run.model_dump(by_alias=True)
    data["_id"] = str(data["_id"])
    for key in ("createdAt", "updatedAt", "startedAt", "finishedAt"):
        value = data.get(key)
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return data


async def _update_post_approval_run(
    db,
    run_id: str,
    *,
    status: Optional[PostApprovalRunStatus] = None,
    stage: Optional[PostApprovalRunStage] = None,
    message: Optional[str] = None,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
    source_file_id: Optional[str] = None,
    output_file_id: Optional[str] = None,
    reconciliation_count: Optional[int] = None,
    stats: Optional[dict[str, Any]] = None,
    errors: Optional[list[Any]] = None,
) -> None:
    update: dict[str, Any] = {"updatedAt": datetime.now(timezone.utc)}
    if status is not None:
        update["status"] = status.value
    if stage is not None:
        update["stage"] = stage.value
    if message is not None:
        update["message"] = message
    if started_at is not None:
        update["startedAt"] = started_at
    if finished_at is not None:
        update["finishedAt"] = finished_at
    if source_file_id is not None:
        update["sourceFileId"] = source_file_id
    if output_file_id is not None:
        update["outputFileId"] = output_file_id
    if reconciliation_count is not None:
        update["reconciliationCount"] = reconciliation_count
    if stats is not None:
        update["stats"] = stats
    if errors is not None:
        update["errors"] = errors
    await PostApprovalRunRepository(db).collection.update_one({"_id": run_id}, {"$set": update})


ScheduleBackground = Callable[[Awaitable[None]], None]


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
    if config is None or config.status != MappingConfigStatus.PENDING_APPROVAL:
        return None

    now = datetime.now(timezone.utc)
    current_approved = await mapping_repo.find_by_partner_and_type(
        config.partner, config.workflow_type, config.file_type
    )
    if current_approved is not None:
        await mapping_repo.collection.update_one(
            {"_id": str(current_approved.id)},
            {"$set": {
                "status": MappingConfigStatus.SUPERSEDED.value,
                "supersededAt": now,
                "supersededByConfigId": str(config.id),
            }},
        )
    health = dict(config.config_health or {})
    health.update(
        {
            "stale": False,
            "status": MappingConfigStatus.APPROVED.value,
            "approvedAt": now,
            "reasoning": (health.get("reasoning") or "Approved from review packet."),
        }
    )
    await mapping_repo.collection.update_one(
        {"_id": packet.draft_mapping_id},
        {"$set": {
            "status": MappingConfigStatus.APPROVED.value,
            "approvedAt": now,
            "approvedBy": reviewed_by,
            "configHealth": health,
        }},
    )
    config.status = MappingConfigStatus.APPROVED
    config.approved_at = now
    config.approved_by = reviewed_by
    config.config_health = health

    if getattr(packet, "backfill_run_id", None):
        gateway = workflow_gateway
        if gateway is None:
            if settings.automation_orchestrator != "airflow":
                raise ReviewUnavailableError(
                    "Backfill approval requires the Airflow orchestrator."
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
            approved_mapping_version_finder=lambda _partner: asyncio.sleep(0, result=config.config_version),
        )
        backfill_run = await service.resume_after_approval(
            backfill_run_id=str(packet.backfill_run_id),
            mapping_version=str(config.config_version or ""),
        )
        return {"backfillRun": serialize_backfill_run(backfill_run)}

    return await _queue_post_approval_reprocess(
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
    """Queue replay for a scope-approved stream that keeps its active mapping."""
    config_id = getattr(packet, "active_runtime_config_id", None)
    if not config_id:
        return None
    config = await MappingConfigRepository(db).find_one({"_id": config_id})
    if config is None or config.status != MappingConfigStatus.APPROVED:
        return None
    return await _queue_post_approval_reprocess(
        db,
        packet,
        config,
        schedule_background=schedule_background,
    )


async def _queue_post_approval_reprocess(
    db,
    packet,
    config,
    *,
    schedule_background: ScheduleBackground,
) -> dict:
    run = PostApprovalRun(
        packetId=str(packet.id),
        partner=packet.partner,
        date=business_date(packet.reconciliation_date).isoformat() if getattr(packet, "reconciliation_date", None) else None,
        status=PostApprovalRunStatus.QUEUED,
        stage=PostApprovalRunStage.APPROVAL,
        message="Approved. Post-approval processing is queued.",
        sourceFileId=getattr(packet, "source_file_id", None),
    )
    await PostApprovalRunRepository(db).create(run)
    schedule_background(
        _run_post_approval_reprocess(
            db,
            str(run.id),
            str(packet.id),
            str(config.id),
        )
    )
    return serialize_post_approval_run(run)


async def _run_post_approval_reprocess(db, run_id: str, packet_id: str, config_id: str) -> None:
    packet_repo = ReviewPacketRepository(db)
    mapping_repo = MappingConfigRepository(db)
    packet = await packet_repo.find_one({"_id": packet_id})
    config = await mapping_repo.find_one({"_id": config_id})
    if packet is None or config is None:
        await _update_post_approval_run(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.APPROVAL,
            message="Packet or approved mapping could not be loaded for post-approval processing.",
            finished_at=datetime.now(timezone.utc),
        )
        return
    try:
        await reprocess_and_reconcile(db, packet, config, run_id)
    except Exception as exc:
        summarized_error = summarize_runtime_error(exc)
        await _update_post_approval_run(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            message=f"Post-approval processing failed: {summarized_error}",
            finished_at=datetime.now(timezone.utc),
            errors=[summarized_error],
        )


async def reprocess_and_reconcile(db, packet, config, run_id: str) -> dict | None:
    runtime_run = await create_runtime_run(
        db,
        partner=config.partner,
        date=business_date(packet.reconciliation_date).isoformat(),
        trigger_type=PartnerRuntimeTriggerType.POST_APPROVAL_REPROCESS,
        triggered_by="system:post-approval",
        status=PartnerRuntimeRunStatus.INGESTING,
        message="Approved file is queued for ingestion.",
        source_file_id=getattr(packet, "source_file_id", None),
        mapping_version=getattr(config, "config_version", None) or str(getattr(config, "id", "")),
        validation_state="NOT_RUN",
    )
    runtime_run_id = str(runtime_run.id)
    source_file_path = getattr(packet, "source_file_path", None)
    source_file_id = getattr(packet, "source_file_id", None)
    raw_stage_key = getattr(packet, "raw_stage_key", None)
    if raw_stage_key:
        staged_result = await _reprocess_staged_pages(
            db=db,
            packet=packet,
            config=config,
            run_id=run_id,
            runtime_run_id=runtime_run_id,
            raw_stage_key=raw_stage_key,
        )
        if staged_result is not None:
            return staged_result
    if not source_file_path or not source_file_id:
        await update_runtime_run(
            db,
            runtime_run_id,
            status=PartnerRuntimeRunStatus.FAILED,
            message="Review packet has no source file attached for post-approval processing.",
            finished_at=datetime.now(timezone.utc),
        )
        await _update_post_approval_run(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.APPROVAL,
            message="Review packet has no source file attached for post-approval processing.",
            finished_at=datetime.now(timezone.utc),
        )
        return None

    try:
        resolved_source_path = resolve_review_source_file(packet)
    except (FileNotFoundError, ValueError):
        await update_runtime_run(
            db,
            runtime_run_id,
            status=PartnerRuntimeRunStatus.FAILED,
            message=f"Source file is no longer available at {source_file_path}.",
            finished_at=datetime.now(timezone.utc),
        )
        await _update_post_approval_run(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.APPROVAL,
            message=f"Source file is no longer available at {source_file_path}.",
            finished_at=datetime.now(timezone.utc),
        )
        return None

    file_repo = ReconciliationFileRepository(db)
    source_file = await file_repo.find_one({"_id": source_file_id})
    if source_file is None:
        await update_runtime_run(
            db,
            runtime_run_id,
            status=PartnerRuntimeRunStatus.FAILED,
            message=f"Source file record {source_file_id} was not found.",
            finished_at=datetime.now(timezone.utc),
        )
        await _update_post_approval_run(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.APPROVAL,
            message=f"Source file record {source_file_id} was not found.",
            finished_at=datetime.now(timezone.utc),
        )
        return None

    # PostgreSQL is the canonical transaction store.
    await DataContainerRepository(db).delete_by_source_file(source_file_id)
    date_str = business_date(source_file.reconciliation_date).isoformat()
    await ReconciliationResultRepository(db).delete_by_partner_and_date(
        config.partner,
        date_str,
    )
    
    if source_file.processing_status != ProcessingStatus.COMPLETED:
        await file_repo.delete_one({"_id": source_file_id})

    await _update_post_approval_run(
        db,
        run_id,
        status=PostApprovalRunStatus.INGESTING,
        stage=PostApprovalRunStage.INGESTION,
        message="Ingesting partner file with the approved mapping.",
        started_at=datetime.now(timezone.utc),
    )
    await update_runtime_run(
        db,
        runtime_run_id,
        status=PartnerRuntimeRunStatus.INGESTING,
        message="Ingesting partner file with the approved mapping.",
        started_at=datetime.now(timezone.utc),
    )

    from src.config.settings import settings
    pipeline = build_ingestion_pipeline(
        db=db,
        config_loader=build_config_loader(db),
        batch_size=settings.ingest_batch_size,
        logger=None,
        fast_mode=True,
    )
    ingestion_result = await pipeline.process_file(
        file_path=resolved_source_path,
        partner=config.partner,
        workflow_type=config.workflow_type,
        file_type=config.file_type,
        reconciliation_date=source_file.reconciliation_date,
        config_version=config.config_version,
        # Guided Review reprocessing is a new delivery attempt, but it does
        # not come through the fetcher. Supply a deterministic fetch-unit
        # identity so the unique Mongo index never receives null.
        fetch_unit_metadata={
            "sourceEndpoint": f"review://{source_file_id}",
            "cursor": f"post-approval:{run_id}",
            "windowStart": source_file.reconciliation_date.isoformat(),
            "windowEnd": source_file.reconciliation_date.isoformat(),
        },
        enable_config_health_check=False,
    )
    processing_status = getattr(
        ingestion_result.file_record.processing_status,
        "value",
        ingestion_result.file_record.processing_status,
    )
    if processing_status == ProcessingStatus.COMPLETED.value:
        await _rebind_replacement_transactions(
            db=db,
            packet=packet,
            config=config,
            ingestion_result=ingestion_result,
            source_file_id=str(ingestion_result.file_record.id),
        )
    result = {
        "ok": processing_status == ProcessingStatus.COMPLETED.value,
        "stage": "ingestion",
        "partner": config.partner,
        "date": business_date(source_file.reconciliation_date).isoformat(),
        "processingStatus": processing_status,
        "fileId": str(ingestion_result.file_record.id),
        "stats": {
            "totalRows": ingestion_result.stats.total_rows,
            "successRows": ingestion_result.stats.success_rows,
            "duplicateRows": ingestion_result.stats.duplicate_rows,
            "failedRows": ingestion_result.stats.failed_rows,
        },
        "errors": ingestion_result.errors,
    }
    if processing_status != ProcessingStatus.COMPLETED.value:
        await update_runtime_run(
            db,
            runtime_run_id,
            status=PartnerRuntimeRunStatus.FAILED,
            message="Ingestion failed after approval.",
            source_file_id=str(ingestion_result.file_record.id),
            stats=result["stats"],
            finished_at=datetime.now(timezone.utc),
        )
        await _update_post_approval_run(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.INGESTION,
            message="Ingestion failed after approval.",
            finished_at=datetime.now(timezone.utc),
            output_file_id=str(ingestion_result.file_record.id),
            stats=result["stats"],
            errors=ingestion_result.errors,
        )
        return result

    if packet.scope_type:
        await file_repo.update_one(
            {"_id": str(ingestion_result.file_record.id)},
            {"scopeType": packet.scope_type},
        )

    await _update_post_approval_run(
        db,
        run_id,
        status=PostApprovalRunStatus.RECONCILING,
        stage=PostApprovalRunStage.RECONCILIATION,
        message="Reconciling ingested partner rows against internal transactions.",
        output_file_id=str(ingestion_result.file_record.id),
        stats=result["stats"],
        errors=ingestion_result.errors,
    )
    await update_runtime_run(
        db,
        runtime_run_id,
        status=PartnerRuntimeRunStatus.RECONCILING,
        message="Reconciling ingested partner rows against internal transactions.",
        source_file_id=str(ingestion_result.file_record.id),
        stats=result["stats"],
    )

    recon_date = source_file.reconciliation_date
    recon_results = await build_reconciliation_service(db, fast_mode=True).execute(
        ReconciliationCommand(
            partner=config.partner,
            reconciliation_date=recon_date,
            source_file_id=str(ingestion_result.file_record.id),
            reconciliation_run_id=runtime_run_id,
            mapping_version=getattr(config, "config_version", None) or str(config.id),
        )
    )

    await _update_post_approval_run(
        db,
        run_id,
        stage=PostApprovalRunStage.CACHE_INVALIDATION,
        message="Invalidating insight cache after reconciliation.",
        output_file_id=str(ingestion_result.file_record.id),
        reconciliation_count=len(recon_results),
        stats={**result["stats"], "resultCount": len(recon_results), "reconciliationCount": len(recon_results)},
    )

    invalidated = await invalidate_insight_cache(
        config.partner,
        recon_date.strftime("%Y-%m-%d"),
    )
    result.update(
        {
            "stage": "reconciliation",
            "reconciliationCount": len(recon_results),
            "insightCacheInvalidated": invalidated,
        }
    )
    await _update_post_approval_run(
        db,
        run_id,
        status=PostApprovalRunStatus.COMPLETED,
        stage=PostApprovalRunStage.CACHE_INVALIDATION,
        message="Post-approval processing completed successfully.",
        finished_at=datetime.now(timezone.utc),
        output_file_id=str(ingestion_result.file_record.id),
        reconciliation_count=len(recon_results),
        stats={**result["stats"], "resultCount": len(recon_results), "reconciliationCount": len(recon_results)},
        errors=ingestion_result.errors,
    )
    await update_runtime_run(
        db,
        runtime_run_id,
        status=PartnerRuntimeRunStatus.COMPLETED,
        message="Reconciliation completed successfully.",
        source_file_id=str(ingestion_result.file_record.id),
        stats={"resultCount": len(recon_results), **result["stats"]},
        reconciliation_count=len(recon_results),
        finished_at=datetime.now(timezone.utc),
    )
    return result


async def _reprocess_staged_pages(
    *,
    db,
    packet,
    config,
    run_id: str,
    runtime_run_id: str,
    raw_stage_key: str,
) -> dict | None:
    """Replay every staged API page after mapping approval.

    This path keeps the existing ingestion/reconciliation services intact and
    only changes where the input file comes from: GridFS instead of a local
    fetch volume. Pages are consumed one by one, so memory stays bounded.
    """
    raw_repo = RawIngestionPageRepository(db)
    pages = await raw_repo.find_for_replay(raw_stage_key)
    if not pages:
        return None

    from src.config.settings import settings

    file_repo = ReconciliationFileRepository(db)
    old_files = await file_repo.find_many(
        {"fetchUnitMetadata.rawStageKey": raw_stage_key}
    )
    transaction_repo = DataContainerRepository(db)
    for old_file in old_files:
        await transaction_repo.delete_by_source_file(str(old_file.id))
    await ReconciliationResultRepository(db).delete_by_partner_and_date(
        config.partner,
        business_date(packet.reconciliation_date).isoformat(),
    )
    if old_files:
        await file_repo.collection.delete_many(
            {"fetchUnitMetadata.rawStageKey": raw_stage_key}
        )

    await _update_post_approval_run(
        db,
        run_id,
        status=PostApprovalRunStatus.INGESTING,
        stage=PostApprovalRunStage.INGESTION,
        message=f"Replaying {len(pages)} staged raw API pages with the approved mapping.",
        started_at=datetime.now(timezone.utc),
    )
    await update_runtime_run(
        db,
        runtime_run_id,
        status=PartnerRuntimeRunStatus.INGESTING,
        message=f"Replaying {len(pages)} staged raw API pages with the approved mapping.",
        started_at=datetime.now(timezone.utc),
    )

    pipeline = build_ingestion_pipeline(
        db=db,
        config_loader=build_config_loader(db),
        batch_size=settings.ingest_batch_size,
        logger=None,
        fast_mode=True,
    )
    total_rows = success_rows = duplicate_rows = failed_rows = 0
    logical_source_file_id: str | None = None
    processed_page_ids: list[str] = []
    ingestion_keys: list[str] = []
    expected_row_count = sum(getattr(page, "item_count", 0) or 0 for page in pages)
    errors: list[Any] = []
    temp_dir = Path(settings.upload_tmp_dir) / f"raw-stage-{run_id}"

    for page in pages:
        destination = temp_dir / Path(page.local_path or f"page-{page.page or 0}.json").name
        path = await raw_repo.materialize(page, str(destination))
        ingestion_result = await pipeline.process_file(
            file_path=path,
            partner=config.partner,
            workflow_type=config.workflow_type,
            file_type=config.file_type,
            reconciliation_date=page.reconciliation_date,
            config_version=config.config_version,
            fetch_unit_metadata={
                "sourceEndpoint": packet.file_name,
                "sourceUnitKey": page.source_unit_key,
                "rawStageKey": raw_stage_key,
                "cursor": page.cursor_before,
                "windowStart": page.reconciliation_date.isoformat(),
                "windowEnd": page.reconciliation_date.isoformat(),
                "sampleRows": page.sample_rows,
            },
            enable_config_health_check=False,
        )
        file_record = ingestion_result.file_record
        status = getattr(
            getattr(file_record, "processing_status", ProcessingStatus.FAILED),
            "value",
            getattr(file_record, "processing_status", ProcessingStatus.FAILED),
        )
        stats = ingestion_result.stats
        total_rows += getattr(stats, "total_rows", 0)
        success_rows += getattr(stats, "success_rows", 0)
        duplicate_rows += getattr(stats, "duplicate_rows", 0)
        failed_rows += getattr(stats, "failed_rows", 0)
        errors.extend(ingestion_result.errors or [])
        ingestion_keys.extend(getattr(ingestion_result, "ingestion_keys", None) or [])
        if status != ProcessingStatus.COMPLETED.value:
            message = "Staged raw page ingestion failed after approval."
            if logical_source_file_id:
                await transaction_repo.delete_by_source_file(logical_source_file_id)
                await file_repo.update_one(
                    {"_id": logical_source_file_id},
                    {
                        "processingStatus": ProcessingStatus.FAILED.value,
                        "totalRows": total_rows,
                        "successRows": success_rows,
                        "failedRows": failed_rows,
                        "fetchUnitMetadata": {
                            "sourceEndpoint": packet.file_name,
                            "rawStageKey": raw_stage_key,
                            "pageCount": len(pages),
                            "processedPageCount": len(processed_page_ids),
                            "pageIds": processed_page_ids,
                            "expectedRowCount": expected_row_count,
                            "actualRowCount": total_rows,
                        },
                    },
                )
            if file_record is not None:
                current_file_id = str(file_record.id)
                if current_file_id != logical_source_file_id:
                    await file_repo.delete_one({"_id": current_file_id})
            await update_runtime_run(
                db,
                runtime_run_id,
                status=PartnerRuntimeRunStatus.FAILED,
                message=message,
                source_file_id=logical_source_file_id,
                stats={
                    "totalRows": total_rows,
                    "successRows": success_rows,
                    "failedRows": failed_rows,
                    "pageCount": len(pages),
                    "processedPageCount": len(processed_page_ids),
                    "expectedRowCount": expected_row_count,
                },
                finished_at=datetime.now(timezone.utc),
            )
            await _update_post_approval_run(
                db,
                run_id,
                status=PostApprovalRunStatus.FAILED,
                stage=PostApprovalRunStage.INGESTION,
                message=message,
                finished_at=datetime.now(timezone.utc),
                output_file_id=logical_source_file_id,
                stats={
                    "totalRows": total_rows,
                    "successRows": success_rows,
                    "failedRows": failed_rows,
                    "pageCount": len(pages),
                    "processedPageCount": len(processed_page_ids),
                    "expectedRowCount": expected_row_count,
                },
                errors=errors,
            )
            return {
                "ok": False,
                "stage": "ingestion",
                "processingStatus": status,
                "fileId": logical_source_file_id,
                "stats": {
                    "totalRows": total_rows,
                    "successRows": success_rows,
                    "failedRows": failed_rows,
                    "pageCount": len(pages),
                    "processedPageCount": len(processed_page_ids),
                    "expectedRowCount": expected_row_count,
                },
                "errors": errors,
            }

        page_file_id = str(file_record.id)
        if logical_source_file_id is None:
            logical_source_file_id = page_file_id
        elif page_file_id != logical_source_file_id:
            await transaction_repo.rebind_source_file(
                page_file_id,
                logical_source_file_id,
            )
            await file_repo.delete_one({"_id": page_file_id})

        processed_page_ids.append(str(page.id))
        await raw_repo.mark_consumed(page.source_unit_key)

    if logical_source_file_id is None:
        return None
    await _rebind_replacement_transactions(
        db=db,
        packet=packet,
        config=config,
        ingestion_result=SimpleNamespace(ingestion_keys=ingestion_keys),
        source_file_id=logical_source_file_id,
    )
    scope_type = getattr(packet, "scope_type", None) or "UNCONFIRMED"
    scope_type = getattr(scope_type, "value", scope_type)
    batch_metadata = {
        "sourceEndpoint": packet.file_name,
        "rawStageKey": raw_stage_key,
        "pageCount": len(pages),
        "processedPageCount": len(processed_page_ids),
        "pageIds": processed_page_ids,
        "expectedRowCount": expected_row_count,
        "actualRowCount": total_rows,
    }
    await file_repo.update_one(
        {"_id": logical_source_file_id},
        {
            "scopeType": scope_type,
            "processingStatus": ProcessingStatus.PROCESSING.value,
            "totalRows": total_rows,
            "successRows": success_rows,
            "failedRows": failed_rows,
            "duplicateRows": duplicate_rows,
            "fetchUnitMetadata": batch_metadata,
        },
    )
    stats_payload = {
        "totalRows": total_rows,
        "successRows": success_rows,
        "duplicateRows": duplicate_rows,
        "failedRows": failed_rows,
        "pageCount": len(pages),
        "processedPageCount": len(processed_page_ids),
        "expectedRowCount": expected_row_count,
    }
    await _update_post_approval_run(
        db,
        run_id,
        status=PostApprovalRunStatus.RECONCILING,
        stage=PostApprovalRunStage.RECONCILIATION,
        message="All staged pages ingested under one logical reconciliation file.",
        output_file_id=logical_source_file_id,
        stats=stats_payload,
        errors=errors,
    )
    await update_runtime_run(
        db,
        runtime_run_id,
        status=PartnerRuntimeRunStatus.RECONCILING,
        message="Reconciling the complete logical reconciliation file.",
        source_file_id=logical_source_file_id,
        stats=stats_payload,
    )
    try:
        recon_results = await build_reconciliation_service(db, fast_mode=True).execute(
            ReconciliationCommand(
                partner=config.partner,
                reconciliation_date=packet.reconciliation_date,
                source_file_id=logical_source_file_id,
                reconciliation_run_id=runtime_run_id,
                mapping_version=getattr(config, "config_version", None) or str(config.id),
            )
        )
    except Exception as exc:
        error_message = summarize_runtime_error(exc)
        await transaction_repo.delete_by_source_file(logical_source_file_id)
        await ReconciliationResultRepository(db).delete_by_partner_and_date(
            config.partner,
            business_date(packet.reconciliation_date).isoformat(),
        )
        await file_repo.update_one(
            {"_id": logical_source_file_id},
            {
                "processingStatus": ProcessingStatus.FAILED.value,
                "fetchUnitMetadata": {
                    **batch_metadata,
                    "reconciliationError": error_message,
                },
            },
        )
        failure_stats = {
            **stats_payload,
            "resultCount": 0,
            "reconciliationError": error_message,
        }
        await _update_post_approval_run(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.RECONCILIATION,
            message=f"Reconciliation failed after batch ingestion: {error_message}",
            finished_at=datetime.now(timezone.utc),
            output_file_id=logical_source_file_id,
            stats=failure_stats,
            errors=[*errors, {"reason": error_message}],
        )
        await update_runtime_run(
            db,
            runtime_run_id,
            status=PartnerRuntimeRunStatus.FAILED,
            message=f"Reconciliation failed after batch ingestion: {error_message}",
            source_file_id=logical_source_file_id,
            stats=failure_stats,
            finished_at=datetime.now(timezone.utc),
        )
        return {
            "ok": False,
            "stage": "reconciliation",
            "partner": config.partner,
            "date": business_date(packet.reconciliation_date).isoformat(),
            "processingStatus": ProcessingStatus.FAILED.value,
            "fileId": logical_source_file_id,
            "stats": failure_stats,
            "errors": [*errors, {"reason": error_message}],
        }
    reconciliation_count = len(recon_results)
    await file_repo.update_one(
        {"_id": logical_source_file_id},
        {"processingStatus": ProcessingStatus.COMPLETED.value},
    )
    stats_payload = {
        "totalRows": total_rows,
        "successRows": success_rows,
        "duplicateRows": duplicate_rows,
        "failedRows": failed_rows,
        "pageCount": len(pages),
        "processedPageCount": len(processed_page_ids),
        "expectedRowCount": expected_row_count,
        "resultCount": reconciliation_count,
    }
    await _update_post_approval_run(
        db,
        run_id,
        status=PostApprovalRunStatus.COMPLETED,
        stage=PostApprovalRunStage.RECONCILIATION,
        message="All staged raw API pages were grouped, ingested, and reconciled.",
        finished_at=datetime.now(timezone.utc),
        output_file_id=logical_source_file_id,
        reconciliation_count=reconciliation_count,
        stats=stats_payload,
        errors=errors,
    )
    await update_runtime_run(
        db,
        runtime_run_id,
        status=PartnerRuntimeRunStatus.COMPLETED,
        message="All staged raw API pages were grouped and reconciled successfully.",
        source_file_id=logical_source_file_id,
        stats=stats_payload,
        reconciliation_count=reconciliation_count,
        finished_at=datetime.now(timezone.utc),
    )
    return {
        "ok": True,
        "stage": "reconciliation",
        "partner": config.partner,
        "date": business_date(packet.reconciliation_date).isoformat(),
        "processingStatus": ProcessingStatus.COMPLETED.value,
        "fileId": logical_source_file_id,
        "stats": stats_payload,
        "reconciliationCount": reconciliation_count,
        "errors": errors,
    }
