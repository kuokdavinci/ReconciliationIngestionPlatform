"""Replay staged raw pages as one logical post-approval batch."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from src.application.runtime.service import update_runtime_run
from src.config.settings import settings
from src.core.utils import business_date, summarize_runtime_error
from src.core.enums import ProcessingStatus
from src.domain.ingestion.checkpoints import IngestionMode
from src.domain.review.models import (
    PostApprovalQualityGateStatus,
    PostApprovalRunStage,
    PostApprovalRunStatus,
)
from src.domain.runtime.models import PartnerRuntimeRunStatus
from src.infrastructure.ingestion.composition import build_ingestion_pipeline
from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository
from src.infrastructure.ingestion.raw_page_repository import RawIngestionPageRepository
from src.infrastructure.ingestion.checkpoint_repository import IngestionCheckpointRepository
from src.infrastructure.ingestion.quarantine_repository import IngestionQuarantineRepository
from src.infrastructure.mapping.composition import build_config_loader
from src.infrastructure.partner_transaction.repository import DataContainerRepository
from src.infrastructure.postgres.reconciliation_result_repository import ReconciliationResultRepository
from src.infrastructure.reconciliation.composition import build_reconciliation_service
from src.pipeline.run_state import IngestionRunState
from src.application.review.post_approval_reconciliation import (
    _batch_fatal_quality_summary,
    _update_runtime_observation,
    _persist_packet_quality_gate,
    _quarantine_quality_gate,
    rebind_replacement_transactions as _rebind_replacement_transactions,
    update_post_approval_run as _update_post_approval_run,
)


async def _finalize_scheduled_checkpoint_after_replay(
    db: Any,
    pages: list[Any],
) -> bool | None:
    if not pages:
        return None

    final_page = pages[-1]
    fetch_config_id = getattr(final_page, "fetch_config_id", None)
    source_type = getattr(final_page, "source_type", None)
    stream_key = getattr(final_page, "stream_key", None)
    unit_key = getattr(final_page, "source_unit_key", None)
    if not isinstance(fetch_config_id, str) or not fetch_config_id:
        return None
    if not isinstance(source_type, str) or not source_type:
        return None
    if not isinstance(stream_key, str) or not stream_key:
        return None
    if not isinstance(unit_key, str) or not unit_key:
        return None

    try:
        checkpoint_repo = IngestionCheckpointRepository(db)
        checkpoint = await checkpoint_repo.find_by_stream(
            partner=final_page.partner,
            fetch_config_id=fetch_config_id,
            source_type=source_type,
            stream_key=stream_key,
            mode=IngestionMode.SCHEDULED,
        )
    except (AttributeError, TypeError):
        # Compatibility doubles and legacy adapters may not expose the
        # checkpoint collection. The completed source file remains the
        # fallback duplicate guard for those environments.
        return None
    if checkpoint is None:
        return None

    try:
        return bool(
            await checkpoint_repo.mark_stream_completed_after_review(
                checkpoint,
                unit_key=unit_key,
                cursor_after=getattr(final_page, "cursor_after", None),
                high_water_mark={
                    "sourceUnitKey": unit_key,
                    "page": getattr(final_page, "page", None),
                    "cursorAfter": getattr(final_page, "cursor_after", None),
                    "contentHash": getattr(final_page, "content_hash", None),
                    "hasMore": getattr(final_page, "has_more", None),
                },
                completed_units=[
                    {
                        "unitKey": page.source_unit_key,
                        "page": page.page,
                        "cursorBefore": page.cursor_before,
                        "cursorAfter": page.cursor_after,
                    }
                    for page in pages
                ],
            )
        )
    except (AttributeError, TypeError):
        return None


async def _mark_replay_checkpoint_failed(
    db: Any,
    page: Any,
    *,
    error: str,
    error_code: str,
) -> bool | None:
    """Keep checkpoint recovery aligned with a failed staged replay."""
    try:
        checkpoint_repo = IngestionCheckpointRepository(db)
        checkpoint = await checkpoint_repo.find_by_stream(
            partner=page.partner,
            fetch_config_id=page.fetch_config_id,
            source_type=page.source_type,
            stream_key=page.stream_key,
            mode=IngestionMode.SCHEDULED,
        )
        if checkpoint is None:
            return None
        return bool(
            await checkpoint_repo.mark_stream_failed_after_review(
                checkpoint,
                unit_key=page.source_unit_key,
                error=error,
                error_code=error_code,
            )
        )
    except (AttributeError, TypeError):
        return None

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
    quarantine_repo: IngestionQuarantineRepository | None = None
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
    runtime_state = IngestionRunState(
        run_id=runtime_run_id,
        partner=config.partner,
        attempt=1,
    )

    await updater(
        db,
        run_id,
        status=PostApprovalRunStatus.INGESTING,
        stage=PostApprovalRunStage.INGESTION,
        message=f"Replaying {len(pages)} staged raw API pages with the approved mapping.",
        started_at=datetime.now(timezone.utc),
    )
    await _update_runtime_observation(
        runtime_updater,
        db,
        runtime_run_id,
        partner=config.partner,
        status=PartnerRuntimeRunStatus.INGESTING,
        message=f"Replaying {len(pages)} staged raw API pages with the approved mapping.",
        stage_summary=runtime_state.stage_summary,
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
    rejected_rows = persistence_failed_rows = quarantined_rows = 0
    partial_seen = False
    logical_source_file_id: str | None = None
    processed_page_ids: list[str] = []
    source_unit_keys: list[str] = []
    ingestion_keys: list[str] = []
    page_item_counts: list[int | None] = [
        count if isinstance(count := getattr(page, "item_count", None), int) else None
        for page in pages
    ]
    has_expected_row_count = bool(pages) and all(
        isinstance(count, int) and count >= 0 for count in page_item_counts
    )
    expected_row_count = (
        sum(count for count in page_item_counts if count is not None)
        if has_expected_row_count
        else None
    )
    errors: list[Any] = []
    temp_dir = Path(settings.upload_tmp_dir) / f"raw-stage-{run_id}"
    for page in pages:
        source_unit_keys.append(page.source_unit_key)
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
                "reviewPacketId": str(packet.id),
                "postApprovalRunId": run_id,
                "sourceFileId": logical_source_file_id,
                "cursor": page.cursor_before,
                "page": page.page,
                "windowStart": page.reconciliation_date.isoformat(),
                "windowEnd": page.reconciliation_date.isoformat(),
                "sampleRows": page.sample_rows,
            },
            enable_config_health_check=False,
            run_id=runtime_run_id,
            attempt=1,
        )
        orchestration_action = getattr(
            getattr(ingestion_result, "orchestration_action", None),
            "value",
            getattr(ingestion_result, "orchestration_action", None),
        )
        file_record = ingestion_result.file_record
        status = getattr(
            getattr(file_record, "processing_status", ProcessingStatus.FAILED),
            "value",
            getattr(file_record, "processing_status", ProcessingStatus.FAILED),
        )
        if file_record is not None:
            page_stage_summary = getattr(file_record, "stage_summary", None) or {}
            runtime_state.merge_stage_summary(page_stage_summary)
            runtime_state.set_source_context(
                source_file_id=str(file_record.id),
                source_unit_key=page.source_unit_key,
                page=page.page,
            )
        stats = ingestion_result.stats
        total_rows += getattr(stats, "total_rows", 0)
        success_rows += getattr(stats, "success_rows", 0)
        duplicate_rows += getattr(stats, "duplicate_rows", 0)
        failed_rows += getattr(stats, "failed_rows", 0)
        quality_counters = getattr(ingestion_result, "quality_counters", {}) or {}
        rejected_rows += int(quality_counters.get("rejectedRows", 0) or 0)
        persistence_failed_rows += int(
            quality_counters.get("persistenceFailedRows", 0) or 0
        )
        quarantined_rows += int(quality_counters.get("quarantinedRows", 0) or 0)
        partial_seen = partial_seen or status == ProcessingStatus.PARTIAL.value
        runtime_state.total_rows = total_rows
        runtime_state.success_rows = success_rows
        runtime_state.failed_rows = failed_rows
        runtime_state.duplicate_rows = duplicate_rows
        runtime_state.rejected_rows = rejected_rows
        runtime_state.persistence_failed_rows = persistence_failed_rows
        runtime_state.quarantined_rows = quarantined_rows
        errors.extend(ingestion_result.errors or [])
        ingestion_keys.extend(getattr(ingestion_result, "ingestion_keys", None) or [])
        if status not in {
            ProcessingStatus.COMPLETED.value,
            ProcessingStatus.PARTIAL.value,
        }:
            message = "Staged raw page ingestion failed after approval."
            batch_fatal_summary = _batch_fatal_quality_summary(ingestion_result)
            ingestion_error = {
                "errorCode": "staged_page_ingestion_failed",
                "reason": message,
                "sourceUnitKey": page.source_unit_key,
            }
            errors = [*errors, ingestion_error]
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
            failure_stats: dict[str, Any] = {
                "totalRows": total_rows,
                "successRows": success_rows,
                "failedRows": failed_rows,
                "pageCount": len(pages),
                "processedPageCount": len(processed_page_ids),
                "expectedRowCount": expected_row_count,
                "actualRowCount": total_rows,
                "sourceUnitKeys": source_unit_keys,
            }
            if batch_fatal_summary is not None:
                await _persist_packet_quality_gate(
                    db,
                    packet,
                    run_id,
                    PostApprovalQualityGateStatus.FAIL,
                    batch_fatal_summary,
                )
                failure_stats["qualityGate"] = batch_fatal_summary
                message = "Post-approval quality gate failed before reconciliation."
            await _mark_replay_checkpoint_failed(
                db,
                page,
                error=message,
                error_code="staged_page_ingestion_failed",
            )
            runtime_state.finish_run()
            await _update_runtime_observation(
                runtime_updater,
                db,
                runtime_run_id,
                partner=config.partner,
                status=PartnerRuntimeRunStatus.FAILED,
                message=message,
                error_code="staged_page_ingestion_failed",
                stage_summary=runtime_state.stage_summary,
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
                quality_gate_status=(
                    PostApprovalQualityGateStatus.FAIL
                    if batch_fatal_summary is not None
                    else None
                ),
                quality_gate_summary=batch_fatal_summary,
            )
            result = {
                "ok": False,
                "stage": "ingestion",
                "processingStatus": status,
                "fileId": logical_source_file_id,
                "stats": failure_stats,
                "errors": errors,
            }
            if batch_fatal_summary is not None:
                result["qualityGateStatus"] = PostApprovalQualityGateStatus.FAIL.value
                result["qualityGateSummary"] = batch_fatal_summary
            return result

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
            if orchestration_action == "HOLD_FOR_REVIEW":
                quarantine_repo = quarantine_repo or IngestionQuarantineRepository(db)
                await quarantine_repo.rebind_source_file(
                    page_file_id,
                    logical_source_file_id,
                )
            await file_repo.delete_one({"_id": page_file_id})

        waiting_for_review = (
            orchestration_action == "HOLD_FOR_REVIEW"
            or getattr(ingestion_result, "outcome", None) == "WAITING_REVIEW"
        )
        if waiting_for_review:
            quality_gate_status, quality_gate_summary = await _quarantine_quality_gate(
                db,
                packet_id=str(packet.id),
                run_id=run_id,
                source_file_id=logical_source_file_id,
            )
            await _persist_packet_quality_gate(
                db,
                packet,
                run_id,
                quality_gate_status,
                quality_gate_summary,
            )
            review_stats = {
                "totalRows": total_rows,
                "successRows": success_rows,
                "duplicateRows": duplicate_rows,
                "failedRows": failed_rows,
                "pageCount": len(pages),
                "processedPageCount": len(processed_page_ids),
                "expectedRowCount": expected_row_count,
                "actualRowCount": total_rows,
                "sourceUnitKeys": source_unit_keys,
                "qualityGate": quality_gate_summary,
            }
            review_error = {
                "errorCode": "conflicting_duplicate_review",
                "reason": "Staged page contains a conflicting duplicate and awaits quarantine review.",
                "sourceUnitKey": page.source_unit_key,
            }
            review_errors = [*errors, review_error]
            await file_repo.update_one(
                {"_id": logical_source_file_id},
                {
                    "processingStatus": ProcessingStatus.PROCESSING.value,
                    "totalRows": total_rows,
                    "successRows": success_rows,
                    "failedRows": failed_rows,
                    "fetchUnitMetadata": {
                        "sourceEndpoint": packet.file_name,
                        "rawStageKey": raw_stage_key,
                        "pageCount": len(pages),
                        "processedPageCount": len(processed_page_ids),
                        "pageIds": processed_page_ids,
                        "sourceUnitKeys": source_unit_keys,
                        "expectedRowCount": expected_row_count,
                        "actualRowCount": total_rows,
                    },
                },
            )
            message = (
                "Staged raw page replay is waiting for quarantine review "
                f"at source unit {page.source_unit_key}."
            )
            runtime_state.finish_run()
            await _update_runtime_observation(
                runtime_updater,
                db,
                runtime_run_id,
                partner=config.partner,
                status=PartnerRuntimeRunStatus.WAITING_REVIEW,
                message=message,
                error_code="conflicting_duplicate_review",
                stage_summary=runtime_state.stage_summary,
                source_file_id=logical_source_file_id,
                stats=review_stats,
                finished_at=datetime.now(timezone.utc),
            )
            await updater(
                db,
                run_id,
                status=PostApprovalRunStatus.WAITING_REVIEW,
                stage=PostApprovalRunStage.INGESTION,
                message=message,
                finished_at=datetime.now(timezone.utc),
                output_file_id=logical_source_file_id,
                stats=review_stats,
                errors=review_errors,
                quality_gate_status=quality_gate_status,
                quality_gate_summary=quality_gate_summary,
            )
            return {
                "ok": False,
                "stage": "ingestion",
                "outcome": "WAITING_REVIEW",
                "waitingForReview": True,
                "partner": config.partner,
                "date": business_date(packet.reconciliation_date).isoformat(),
                "processingStatus": ProcessingStatus.PROCESSING.value,
                "fileId": logical_source_file_id,
                "stats": review_stats,
                "errors": review_errors,
            }

        processed_page_ids.append(str(page.id))
        await raw_repo.mark_consumed(page.source_unit_key)

    if logical_source_file_id is None:
        return None

    if has_expected_row_count and total_rows != expected_row_count:
        completeness_error = {
            "errorCode": "staged_replay_incomplete",
            "reason": (
                "Staged raw page replay row count does not match the durable "
                "source-page count."
            ),
            "expectedRowCount": expected_row_count,
            "actualRowCount": total_rows,
        }
        errors = [*errors, completeness_error]
        failure_stats = {
            "totalRows": total_rows,
            "successRows": success_rows,
            "duplicateRows": duplicate_rows,
            "failedRows": failed_rows,
            "pageCount": len(pages),
            "processedPageCount": len(processed_page_ids),
            "expectedRowCount": expected_row_count,
            "actualRowCount": total_rows,
        }
        await transaction_repo.delete_by_source_file(logical_source_file_id)
        await _mark_replay_checkpoint_failed(
            db,
            pages[-1],
            error=str(completeness_error["reason"]),
            error_code=str(completeness_error["errorCode"]),
        )
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
                    "replayError": completeness_error,
                },
            },
        )
        message = (
            "Staged raw page replay incomplete: "
            f"expected {expected_row_count} rows, ingested {total_rows}."
        )
        runtime_state.finish_run()
        await _update_runtime_observation(
            runtime_updater,
            db,
            runtime_run_id,
            partner=config.partner,
            status=PartnerRuntimeRunStatus.FAILED,
            message=message,
            error_code="staged_replay_incomplete",
            stage_summary=runtime_state.stage_summary,
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
            "partner": config.partner,
            "date": business_date(packet.reconciliation_date).isoformat(),
            "processingStatus": ProcessingStatus.FAILED.value,
            "fileId": logical_source_file_id,
            "stats": failure_stats,
            "errors": errors,
        }

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
        "sourceUnitKeys": source_unit_keys,
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
    stats_payload: dict[str, Any] = {
        "totalRows": total_rows,
        "successRows": success_rows,
        "duplicateRows": duplicate_rows,
        "failedRows": failed_rows,
        "pageCount": len(pages),
        "processedPageCount": len(processed_page_ids),
        "expectedRowCount": expected_row_count,
        "actualRowCount": total_rows,
        "sourceUnitKeys": source_unit_keys,
    }
    quality_gate_status, quality_gate_summary = await _quarantine_quality_gate(
        db,
        packet_id=str(packet.id),
        run_id=run_id,
        source_file_id=logical_source_file_id,
    )
    stats_payload["qualityGate"] = quality_gate_summary
    await _persist_packet_quality_gate(
        db,
        packet,
        run_id,
        quality_gate_status,
        quality_gate_summary,
    )
    if quality_gate_status.value == "REVIEW_REQUIRED":
        active_rows = quality_gate_summary["activeRows"]
        message = f"{active_rows} quarantine record(s) require review before reconciliation."
        await updater(
            db,
            run_id,
            status=PostApprovalRunStatus.WAITING_REVIEW,
            stage=PostApprovalRunStage.INGESTION,
            message=message,
            output_file_id=logical_source_file_id,
            stats=stats_payload,
            errors=errors,
            quality_gate_status=quality_gate_status,
            quality_gate_summary=quality_gate_summary,
        )
        await _update_runtime_observation(
            runtime_updater,
            db,
            runtime_run_id,
            partner=config.partner,
            status=PartnerRuntimeRunStatus.WAITING_REVIEW,
            message=message,
            stage_summary=runtime_state.stage_summary,
            source_file_id=logical_source_file_id,
            stats=stats_payload,
        )
        return {
            "ok": False,
            "stage": "ingestion",
            "outcome": "WAITING_REVIEW",
            "waitingForReview": True,
            "partner": config.partner,
            "date": business_date(packet.reconciliation_date).isoformat(),
            "processingStatus": ProcessingStatus.PROCESSING.value,
            "fileId": logical_source_file_id,
            "stats": stats_payload,
            "errors": errors,
            "qualityGateStatus": quality_gate_status.value,
            "qualityGateSummary": quality_gate_summary,
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
        quality_gate_status=quality_gate_status,
        quality_gate_summary=quality_gate_summary,
    )
    await _update_runtime_observation(
        runtime_updater,
        db,
        runtime_run_id,
        partner=config.partner,
        status=PartnerRuntimeRunStatus.RECONCILING,
        message="Reconciling the complete logical reconciliation file.",
        stage_summary=runtime_state.stage_summary,
        source_file_id=logical_source_file_id,
        stats=stats_payload,
    )
    try:
        recon_results = await build_reconciliation_service(db).reconcile(
            config.partner,
            packet.reconciliation_date,
            source_file_id=logical_source_file_id,
            reconciliation_run_id=runtime_run_id,
            mapping_version=getattr(config, "config_version", None) or str(config.id),
        )
    except Exception as exc:
        error_message = summarize_runtime_error(exc)
        await transaction_repo.delete_by_source_file(logical_source_file_id)
        await ReconciliationResultRepository(db).delete_by_partner_and_date(
            config.partner,
            business_date(packet.reconciliation_date).isoformat(),
        )
        await _mark_replay_checkpoint_failed(
            db,
            pages[-1],
            error=f"Reconciliation failed after batch ingestion: {error_message}",
            error_code="reconciliation_failed",
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
        reconciliation_error = {
            "errorCode": "reconciliation_failed",
            "reason": error_message,
        }
        errors = [*errors, reconciliation_error]
        runtime_state.finish_run()
        await updater(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.RECONCILIATION,
            message=f"Reconciliation failed after batch ingestion: {error_message}",
            finished_at=datetime.now(timezone.utc),
            output_file_id=logical_source_file_id,
            stats=failure_stats,
            errors=errors,
        )
        await _update_runtime_observation(
            runtime_updater,
            db,
            runtime_run_id,
            partner=config.partner,
            status=PartnerRuntimeRunStatus.FAILED,
            message=f"Reconciliation failed after batch ingestion: {error_message}",
            error_code="reconciliation_failed",
            stage_summary=runtime_state.stage_summary,
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
            "errors": errors,
        }

    reconciliation_count = len(recon_results)
    checkpoint_finalized = await _finalize_scheduled_checkpoint_after_replay(db, pages)
    if checkpoint_finalized is False:
        checkpoint_error = {
            "errorCode": "checkpoint_finalize_failed",
            "reason": "The staged replay completed, but checkpoint finalization was not persisted.",
        }
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
                    "reconciliationCount": reconciliation_count,
                    "replayError": checkpoint_error,
                },
            },
        )
        failure_stats = {
            **stats_payload,
            "resultCount": reconciliation_count,
            "checkpointFinalized": False,
        }
        message = "Staged replay could not finalize its source checkpoint."
        runtime_state.finish_run()
        await updater(
            db,
            run_id,
            status=PostApprovalRunStatus.FAILED,
            stage=PostApprovalRunStage.RECONCILIATION,
            message=message,
            finished_at=datetime.now(timezone.utc),
            output_file_id=logical_source_file_id,
            reconciliation_count=reconciliation_count,
            stats=failure_stats,
            errors=[*errors, checkpoint_error],
        )
        await _update_runtime_observation(
            runtime_updater,
            db,
            runtime_run_id,
            partner=config.partner,
            status=PartnerRuntimeRunStatus.FAILED,
            message=message,
            error_code="checkpoint_finalize_failed",
            stage_summary=runtime_state.stage_summary,
            source_file_id=logical_source_file_id,
            stats=failure_stats,
            reconciliation_count=reconciliation_count,
            finished_at=datetime.now(timezone.utc),
        )
        return {
            "ok": False,
            "stage": "checkpoint",
            "partner": config.partner,
            "date": business_date(packet.reconciliation_date).isoformat(),
            "processingStatus": ProcessingStatus.FAILED.value,
            "fileId": logical_source_file_id,
            "stats": failure_stats,
            "errors": [*errors, checkpoint_error],
        }

    partial = partial_seen or any(
        count > 0
        for count in (rejected_rows, persistence_failed_rows, quarantined_rows)
    )
    runtime_state.finish_run()
    final_stage_summary = runtime_state.stage_summary
    await file_repo.update_one(
        {"_id": logical_source_file_id},
        {
            "processingStatus": (
                ProcessingStatus.PARTIAL.value
                if partial
                else ProcessingStatus.COMPLETED.value
            ),
            "stageSummary": final_stage_summary,
        },
    )
    stats_payload = {
        **stats_payload,
        "outcome": "PARTIAL" if partial else "INGESTED",
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
    final_runtime_status = (
        PartnerRuntimeRunStatus.PARTIAL
        if partial
        else PartnerRuntimeRunStatus.COMPLETED
    )
    await _update_runtime_observation(
        runtime_updater,
        db,
        runtime_run_id,
        partner=config.partner,
        status=final_runtime_status,
        message=(
            "All staged raw API pages were grouped and reconciled with rejected records."
            if partial
            else "All staged raw API pages were grouped and reconciled successfully."
        ),
        stage_summary=final_stage_summary,
        source_file_id=logical_source_file_id,
        stats=stats_payload,
        reconciliation_count=reconciliation_count,
        finished_at=datetime.now(timezone.utc),
    )
    return {
        "ok": True,
        "stage": "reconciliation",
        "outcome": "PARTIAL" if partial else "INGESTED",
        "partner": config.partner,
        "date": business_date(packet.reconciliation_date).isoformat(),
        "processingStatus": (
            ProcessingStatus.PARTIAL.value if partial else ProcessingStatus.COMPLETED.value
        ),
        "fileId": logical_source_file_id,
        "stats": stats_payload,
        "reconciliationCount": reconciliation_count,
        "errors": errors,
        "stageSummary": final_stage_summary,
    }
