"""Post-approval replay and reconciliation application use cases."""

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from src.analysis.insights import invalidate_insight_cache
from src.application.reconciliation.service import ReconciliationCommand
from src.application.review.raw_stream import resolve_review_source_file
from src.application.runtime.service import create_runtime_run, update_runtime_run
from src.config.settings import settings
from src.core.business_day import business_date
from src.core.error_formatting import summarize_runtime_error
from src.core.enums import ProcessingStatus, ReconciliationScopeType
from src.domain.review.models import (
    PostApprovalRun,
    PostApprovalRunStage,
    PostApprovalRunStatus,
)
from src.domain.runtime.models import PartnerRuntimeRunStatus, PartnerRuntimeTriggerType
from src.infrastructure.ingestion.composition import build_ingestion_pipeline
from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository
from src.infrastructure.ingestion.raw_page_repository import RawIngestionPageRepository
from src.infrastructure.mapping.composition import build_config_loader
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.infrastructure.partner_transaction.repository import DataContainerRepository
from src.infrastructure.postgres.reconciliation_result_repository import (
    ReconciliationResultRepository,
)
from src.infrastructure.reconciliation.composition import build_reconciliation_service
from src.infrastructure.review.repository import (
    PostApprovalRunRepository,
    ReviewPacketRepository,
)


ScheduleBackground = Callable[[Awaitable[None]], None]


async def _rebind_replacement_transactions(
    *,
    db,
    packet,
    config,
    ingestion_result,
    source_file_id: str,
) -> int:
    """Attach deduplicated replacement rows to the current logical file."""
    scope_type = getattr(packet, "scope_type", None)
    scope_type = getattr(scope_type, "value", scope_type)
    if scope_type != ReconciliationScopeType.REPLACEMENT.value:
        return 0

    keys = list(
        dict.fromkeys(
            str(key).strip()
            for key in (getattr(ingestion_result, "ingestion_keys", None) or [])
            if str(key).strip()
        )
    )
    if not keys:
        return 0
    return await DataContainerRepository(db).rebind_source_file_by_ingestion_keys(
        config.partner,
        keys,
        source_file_id,
    )


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
    await PostApprovalRunRepository(db).collection.update_one(
        {"_id": run_id},
        {"$set": update},
    )


async def queue_post_approval_reprocess(
    db,
    packet,
    config,
    *,
    schedule_background: ScheduleBackground,
) -> dict:
    """Create and schedule a durable post-approval replay."""
    run = PostApprovalRun(
        packetId=str(packet.id),
        partner=packet.partner,
        date=(
            business_date(packet.reconciliation_date).isoformat()
            if getattr(packet, "reconciliation_date", None)
            else None
        ),
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


async def _run_post_approval_reprocess(
    db,
    run_id: str,
    packet_id: str,
    config_id: str,
) -> None:
    packet = await ReviewPacketRepository(db).find_one({"_id": packet_id})
    config = await MappingConfigRepository(db).find_one({"_id": config_id})
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
    """Replay a review packet source and reconcile the resulting transactions."""
    runtime_run = await create_runtime_run(
        db,
        partner=config.partner,
        date=business_date(packet.reconciliation_date).isoformat(),
        trigger_type=PartnerRuntimeTriggerType.POST_APPROVAL_REPROCESS,
        triggered_by="system:post-approval",
        status=PartnerRuntimeRunStatus.INGESTING,
        message="Approved file is queued for ingestion.",
        source_file_id=getattr(packet, "source_file_id", None),
        mapping_version=getattr(config, "config_version", None)
        or str(getattr(config, "id", "")),
        validation_state="NOT_RUN",
    )
    runtime_run_id = str(runtime_run.id)
    source_file_path = getattr(packet, "source_file_path", None)
    source_file_id = getattr(packet, "source_file_id", None)
    raw_stage_key = getattr(packet, "raw_stage_key", None)
    if raw_stage_key:
        staged_result = await reprocess_staged_pages(
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

    pipeline = build_ingestion_pipeline(
        db=db,
        config_loader=build_config_loader(db),
        batch_size=settings.ingest_batch_size,
        logger=None,
        fast_mode=True,
    )
    ingestion_result = await pipeline.process_file(
        file_path=str(resolved_source_path),
        partner=config.partner,
        workflow_type=config.workflow_type,
        file_type=config.file_type,
        reconciliation_date=source_file.reconciliation_date,
        config_version=config.config_version,
        fetch_unit_metadata={
            "sourceEndpoint": f"review://{source_file_id}",
            "cursor": f"post-approval:{run_id}",
            "windowStart": source_file.reconciliation_date.isoformat(),
            "windowEnd": source_file.reconciliation_date.isoformat(),
        },
        enable_config_health_check=False,
    )
    file_record = ingestion_result.file_record
    if file_record is None:
        raise RuntimeError("Ingestion did not return a source file record.")
    processing_status = getattr(
        file_record.processing_status,
        "value",
        file_record.processing_status,
    )
    if processing_status == ProcessingStatus.COMPLETED.value:
        await _rebind_replacement_transactions(
            db=db,
            packet=packet,
            config=config,
            ingestion_result=ingestion_result,
            source_file_id=str(file_record.id),
        )
    result = {
        "ok": processing_status == ProcessingStatus.COMPLETED.value,
        "stage": "ingestion",
        "partner": config.partner,
        "date": business_date(source_file.reconciliation_date).isoformat(),
        "processingStatus": processing_status,
        "fileId": str(file_record.id),
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
            source_file_id=str(file_record.id),
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
            output_file_id=str(file_record.id),
            stats=result["stats"],
            errors=ingestion_result.errors,
        )
        return result

    if packet.scope_type:
        await file_repo.update_one(
            {"_id": str(file_record.id)},
            {"scopeType": packet.scope_type},
        )

    await _update_post_approval_run(
        db,
        run_id,
        status=PostApprovalRunStatus.RECONCILING,
        stage=PostApprovalRunStage.RECONCILIATION,
        message="Reconciling ingested partner rows against internal transactions.",
        output_file_id=str(file_record.id),
        stats=result["stats"],
        errors=ingestion_result.errors,
    )
    await update_runtime_run(
        db,
        runtime_run_id,
        status=PartnerRuntimeRunStatus.RECONCILING,
        message="Reconciling ingested partner rows against internal transactions.",
        source_file_id=str(file_record.id),
        stats=result["stats"],
    )

    recon_date = source_file.reconciliation_date
    recon_results = await build_reconciliation_service(db, fast_mode=True).execute(
        ReconciliationCommand(
            partner=config.partner,
            reconciliation_date=recon_date,
            source_file_id=str(file_record.id),
            reconciliation_run_id=runtime_run_id,
            mapping_version=getattr(config, "config_version", None)
            or str(config.id),
        )
    )
    result_count = len(recon_results)
    result_stats = {
        **result["stats"],
        "resultCount": result_count,
        "reconciliationCount": result_count,
    }
    await _update_post_approval_run(
        db,
        run_id,
        stage=PostApprovalRunStage.CACHE_INVALIDATION,
        message="Invalidating insight cache after reconciliation.",
        output_file_id=str(file_record.id),
        reconciliation_count=result_count,
        stats=result_stats,
    )
    invalidated = await invalidate_insight_cache(
        config.partner,
        recon_date.strftime("%Y-%m-%d"),
    )
    result.update(
        {
            "stage": "reconciliation",
            "reconciliationCount": result_count,
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
        output_file_id=str(file_record.id),
        reconciliation_count=result_count,
        stats=result_stats,
        errors=ingestion_result.errors,
    )
    await update_runtime_run(
        db,
        runtime_run_id,
        status=PartnerRuntimeRunStatus.COMPLETED,
        message="Reconciliation completed successfully.",
        source_file_id=str(file_record.id),
        stats={"resultCount": result_count, **result["stats"]},
        reconciliation_count=result_count,
        finished_at=datetime.now(timezone.utc),
    )
    return result


async def reprocess_staged_pages(
    *,
    db,
    packet,
    config,
    run_id: str,
    runtime_run_id: str,
    raw_stage_key: str,
) -> dict | None:
    """Replay staged API pages as one logical reconciliation file."""
    raw_repo = RawIngestionPageRepository(db)
    pages = await raw_repo.find_for_replay(raw_stage_key)
    if not pages:
        return None

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
    expected_row_count = sum(
        getattr(page, "item_count", 0) or 0 for page in pages
    )
    errors: list[Any] = []
    temp_dir = Path(settings.upload_tmp_dir) / f"raw-stage-{run_id}"

    for page in pages:
        destination = temp_dir / Path(
            page.local_path or f"page-{page.page or 0}.json"
        ).name
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
            failure_stats = {
                "totalRows": total_rows,
                "successRows": success_rows,
                "failedRows": failed_rows,
                "pageCount": len(pages),
                "processedPageCount": len(processed_page_ids),
                "expectedRowCount": expected_row_count,
            }
            await update_runtime_run(
                db,
                runtime_run_id,
                status=PartnerRuntimeRunStatus.FAILED,
                message=message,
                source_file_id=logical_source_file_id,
                stats=failure_stats,
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
                stats=failure_stats,
                errors=errors,
            )
            return {
                "ok": False,
                "stage": "ingestion",
                "processingStatus": status,
                "fileId": logical_source_file_id,
                "stats": failure_stats,
                "errors": errors,
            }

        if file_record is None:
            raise RuntimeError("Ingestion did not return a source file record.")
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
                mapping_version=getattr(config, "config_version", None)
                or str(config.id),
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
        **stats_payload,
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


async def reprocess_file(db: Any, packet, config, run_id: str) -> dict | None:
    """Replay a file-level review packet and reconcile its transactions."""
    return await reprocess_and_reconcile(db, packet, config, run_id)


async def start_post_approval_reprocess(
    db: Any,
    packet,
    config,
    *,
    schedule_background: ScheduleBackground,
) -> dict:
    """Create and schedule a durable post-approval operation."""
    return await queue_post_approval_reprocess(
        db,
        packet,
        config,
        schedule_background=schedule_background,
    )
