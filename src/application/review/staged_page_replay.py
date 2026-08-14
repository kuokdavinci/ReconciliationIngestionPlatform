"""Replay staged raw pages as one logical post-approval batch."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from src.application.reconciliation.service import ReconciliationCommand
from src.application.runtime.service import update_runtime_run
from src.config.settings import settings
from src.core.business_day import business_date
from src.core.error_formatting import summarize_runtime_error
from src.core.enums import ProcessingStatus
from src.domain.review.models import PostApprovalRunStage, PostApprovalRunStatus
from src.domain.runtime.models import PartnerRuntimeRunStatus
from src.infrastructure.ingestion.composition import build_ingestion_pipeline
from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository
from src.infrastructure.ingestion.raw_page_repository import RawIngestionPageRepository
from src.infrastructure.mapping.composition import build_config_loader
from src.infrastructure.partner_transaction.repository import DataContainerRepository
from src.infrastructure.postgres.reconciliation_result_repository import ReconciliationResultRepository
from src.infrastructure.reconciliation.composition import build_reconciliation_service
from src.application.review.post_approval_reconciliation import (
    rebind_replacement_transactions as _rebind_replacement_transactions,
    update_post_approval_run as _update_post_approval_run,
)

async def replay_staged_pages(
    *,
    db,
    packet,
    config,
    run_id: str,
    runtime_run_id: str,
    raw_stage_key: str,
    updater: Callable[..., Any] | None = None,
    runtime_updater: Callable[..., Any] | None = None,
    replacement_rebinder: Callable[..., Any] | None = None,
) -> dict | None:
    """Replay staged API pages as one logical reconciliation file."""
    updater = updater or _update_post_approval_run
    runtime_updater = runtime_updater or update_runtime_run
    replacement_rebinder = replacement_rebinder or _rebind_replacement_transactions
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

    await updater(
        db,
        run_id,
        status=PostApprovalRunStatus.INGESTING,
        stage=PostApprovalRunStage.INGESTION,
        message=f"Replaying {len(pages)} staged raw API pages with the approved mapping.",
        started_at=datetime.now(timezone.utc),
    )
    await runtime_updater(
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
            await runtime_updater(
                db,
                runtime_run_id,
                status=PartnerRuntimeRunStatus.FAILED,
                message=message,
                source_file_id=logical_source_file_id,
                stats=failure_stats,
                finished_at=datetime.now(timezone.utc),
            )
            await updater(
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
    await replacement_rebinder(
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
    await updater(
        db,
        run_id,
        status=PostApprovalRunStatus.RECONCILING,
        stage=PostApprovalRunStage.RECONCILIATION,
        message="All staged pages ingested under one logical reconciliation file.",
        output_file_id=logical_source_file_id,
        stats=stats_payload,
        errors=errors,
    )
    await runtime_updater(
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
        await updater(
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
        await runtime_updater(
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
    await updater(
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
    await runtime_updater(
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
