"""Paginated API source stream execution."""

import logging
from pathlib import Path
from typing import Any

from src.application.automation.stream_failure import (
    fetch_error_code,
    paginated_fetch_failure_result,
)
from src.application.automation.stream_runtime import unit_high_water_mark
from src.application.automation.stream_lifecycle import StreamRunContext
from src.application.ingestion.source_unit_orchestrator import resume_held_source_unit
from src.config.config_health import ConfigurationApprovalRequiredError
from src.core.enums import FileType
from src.domain.ingestion.source_units import SourceUnitMetadata

logger = logging.getLogger("reconciliation.automation.paginated_stream_runner")


async def resume_paginated_source_unit(
    *,
    context: StreamRunContext,
    quarantine_repo: Any,
    unit: SourceUnitMetadata,
    ingest_unit: Any | None = None,
) -> dict[str, Any]:
    """Replay one staged API unit after quarantine blockers are resolved."""

    async def consume_after_checkpoint(unit_to_consume: SourceUnitMetadata) -> None:
        if context.stage_key:
            await context.raw_page_repo.mark_consumed(
                unit_to_consume.source_unit_key or ""
            )
        await context.cleanup_unit(unit_to_consume)

    return await resume_held_source_unit(
        context.checkpoint_repo,
        quarantine_repo,
        source_unit_key=unit.source_unit_key or "",
        stream_identity={
            **context.identity,
            "lastCompletedUnitKey": (
                context.checkpoint.last_completed_unit_key
                if context.checkpoint is not None
                else None
            ),
        },
        unit=unit,
        ingest_unit=ingest_unit or context.ingest_unit,
        mode=context.mode,
        retry_policy=context.retry_policy,
        on_unit_completed=consume_after_checkpoint,
    )


async def run_paginated_stream(
    *,
    context: StreamRunContext,
    method_config: Any,
) -> dict[str, Any]:
    """Fetch, stage, review, and ingest one complete paginated API stream."""

    stage_key = context.stage_key
    if stage_key is None:
        raise RuntimeError("API source streams require a raw staging key.")

    identity = context.identity
    checkpoint = context.checkpoint
    checkpoint_repo = context.checkpoint_repo
    retry_policy = context.retry_policy
    dependencies = context.dependencies
    fetch_metadata: dict[str, Any] = {
        "singleUnit": True,
        "configVersion": identity["configVersion"],
    }
    previous_unit_key = checkpoint.last_completed_unit_key if checkpoint else None
    if checkpoint:
        stored_page = (checkpoint.stream_metadata or {}).get("page")
        if getattr(checkpoint.status, "value", checkpoint.status) in {
            "FAILED",
            "PROCESSING",
        } and stored_page:
            fetch_metadata["page"] = stored_page
            fetch_metadata["cursor"] = checkpoint.cursor_before
        elif checkpoint.high_water_mark and checkpoint.high_water_mark.get("page"):
            fetch_metadata["page"] = checkpoint.high_water_mark["page"] + 1
            fetch_metadata["cursor"] = checkpoint.cursor_after

    staged_units: list[SourceUnitMetadata] = []
    raw_staging_available = True
    while True:
        fetch_result = await context.fetcher.fetch(
            method_config,
            context.reconciliation_date,
            fetch_metadata=fetch_metadata,
        )
        if not fetch_result.success:
            if fetch_result.units:
                failed_unit = SourceUnitMetadata.from_payload(fetch_result.units[-1])
                logger.warning(
                    "source_unit_fetch_failed partner=%s runtimeRunId=%s "
                    "streamKey=%s sourceUnitKey=%s page=%s cursorBefore=%s "
                    "statusCode=%s errorCode=%s error=%s",
                    identity["partner"],
                    context.runtime_run_id or "-",
                    identity["streamKey"],
                    failed_unit.source_unit_key or "-",
                    failed_unit.page or "-",
                    failed_unit.cursor_before or "-",
                    failed_unit.status_code or "-",
                    failed_unit.error_code or "-",
                    fetch_result.error or failed_unit.error or "-",
                )

                async def fetch_failure(_: SourceUnitMetadata) -> dict[str, Any]:
                    error_code = failed_unit.error_code or fetch_error_code(fetch_result.error)
                    return dependencies.ingestion_error_result(
                        fetch_result.error or "API source unit fetch failed",
                        error_code,
                        retryable=retry_policy.classify(error_code).value == "RETRYABLE",
                    )

                # Successful pages in the durable-staging path are not claimed
                # until the complete stream has been fetched. The local cursor
                # is the predecessor for a failed page until then.
                can_resume_failed_unit = (
                    checkpoint is not None
                    and checkpoint.last_completed_unit_key == previous_unit_key
                )
                if can_resume_failed_unit:
                    return await dependencies.process_source_units(
                        checkpoint_repo,
                        stream_identity={
                            **identity,
                            "lastCompletedUnitKey": previous_unit_key,
                            "streamMetadata": {"page": failed_unit.page},
                        },
                        units=[failed_unit],
                        ingest_unit=fetch_failure,
                        mode=context.mode,
                        retry_policy=retry_policy,
                        on_unit_completed=context.cleanup_unit,
                    )
                error = (
                    fetch_result.error
                    or failed_unit.error
                    or "API source unit fetch failed"
                )
                error_code = failed_unit.error_code or "fetch_network_error"
                return paginated_fetch_failure_result(
                    error=error,
                    error_code=error_code,
                    fetched_unit_count=len(staged_units),
                    total_unit_count=getattr(
                        method_config.pagination, "max_pages", len(staged_units)
                    ),
                    current_page=failed_unit.page,
                    stopped_at=failed_unit.source_unit_key,
                    include_unit_fields=True,
                    retryable=retry_policy.classify(error_code).value == "RETRYABLE",
                )

            fetch_error = fetch_result.error or "API source unit fetch failed"
            error_code = fetch_error_code(fetch_error, fetch_result.metadata)
            logger.error(
                "source_stream_fetch_failed partner=%s runtimeRunId=%s "
                "streamKey=%s errorCode=%s error=%s",
                identity["partner"],
                context.runtime_run_id or "-",
                identity["streamKey"],
                error_code,
                fetch_error,
            )
            return paginated_fetch_failure_result(
                error=fetch_error,
                error_code=error_code,
                fetched_unit_count=0,
                total_unit_count=getattr(method_config.pagination, "max_pages", 0),
                retryable=retry_policy.classify(error_code).value == "RETRYABLE",
            )

        unit = SourceUnitMetadata.from_payload(fetch_result.units[0])
        pagination = fetch_result.metadata["pagination"]
        logger.info(
            "source_unit_fetched partner=%s runtimeRunId=%s streamKey=%s "
            "sourceUnitKey=%s page=%s cursorBefore=%s cursorAfter=%s "
            "itemCount=%s hasMore=%s",
            identity["partner"],
            context.runtime_run_id or "-",
            identity["streamKey"],
            unit.source_unit_key or "-",
            unit.page or "-",
            unit.cursor_before or "-",
            unit.cursor_after or "-",
            unit.item_count,
            pagination.get("has_more"),
        )
        unit.has_more = pagination.get("has_more")
        unit.high_water_mark = unit_high_water_mark(unit)
        unit.fetch_metadata = {**unit.fetch_metadata, "rawStageKey": stage_key}
        if raw_staging_available:
            raw_staging_available = await dependencies.stage_stream_unit(
                context.raw_page_repo,
                stage_key=stage_key,
                partner=identity["partner"],
                fetch_config_id=identity["fetchConfigId"],
                source_type=identity["sourceType"],
                stream_key=identity["streamKey"],
                reconciliation_date=context.reconciliation_date,
                unit=unit,
            )
        staged_units.append(unit)
        if not raw_staging_available:
            # Keep the legacy one-page-at-a-time path for adapters without
            # durable staging support.
            unit_result = await dependencies.process_source_units(
                checkpoint_repo,
                stream_identity={
                    **identity,
                    "lastCompletedUnitKey": previous_unit_key,
                    "streamMetadata": {"page": unit.page},
                },
                units=[unit],
                ingest_unit=context.ingest_unit,
                mode=context.mode,
                retry_policy=retry_policy,
                on_unit_completed=context.cleanup_unit,
            )
            if (
                not unit_result["success"]
                or unit_result.get("outcome") == "WAITING_REVIEW"
                or unit_result.get("waitingForReview") is True
            ):
                return unit_result
            if not pagination.get("has_more"):
                return unit_result
            previous_unit_key = unit.source_unit_key
            fetch_metadata = {
                "singleUnit": True,
                "page": (unit.page or 0) + 1,
                "cursor": unit.cursor_after,
                "configVersion": identity["configVersion"],
            }
            continue
        if not pagination.get("has_more"):
            break
        previous_unit_key = unit.source_unit_key
        fetch_metadata = {
            "singleUnit": True,
            "page": (unit.page or 0) + 1,
            "cursor": unit.cursor_after,
            "configVersion": identity["configVersion"],
        }

    async def mark_page_consumed(unit: SourceUnitMetadata) -> None:
        if raw_staging_available:
            await context.raw_page_repo.mark_consumed(unit.source_unit_key or "")
        await context.cleanup_unit(unit)

    first_staged_unit = staged_units[0] if staged_units else None
    if first_staged_unit is not None:
        active_runtime_config = None
        try:
            active_runtime_config = await dependencies.evaluate_stream_mapping(
                file_path=first_staged_unit.local_path or "",
                partner=context.config.partner,
                workflow_type="UPC",
                file_type=FileType.SETTLEMENT,
                config_loader=context.config_loader,
                config_repo=dependencies.mapping_config_repository(context.db),
                source_file_name=Path(first_staged_unit.local_path or "").name,
                source_file_path=first_staged_unit.local_path,
                reconciliation_date=context.reconciliation_date,
                raw_stage_key=stage_key,
                backfill_run_id=context.backfill_run_id,
            )
        except ConfigurationApprovalRequiredError as approval_exc:
            review_checkpoint, won_review_claim = await checkpoint_repo.claim_unit(
                partner=identity["partner"],
                fetch_config_id=identity["fetchConfigId"],
                source_type=identity["sourceType"],
                stream_key=identity["streamKey"],
                unit_key=first_staged_unit.source_unit_key or "",
                mode=context.mode,
                cursor_before=first_staged_unit.cursor_before,
                expected_previous_unit_key=(
                    checkpoint.last_completed_unit_key if checkpoint else None
                ),
                config_version=identity["configVersion"],
                source_endpoint=identity["sourceEndpoint"],
                stream_metadata={"page": first_staged_unit.page},
            )
            if won_review_claim:
                await checkpoint_repo.release_for_review(
                    review_checkpoint,
                    unit_key=first_staged_unit.source_unit_key or "",
                    reason=str(approval_exc),
                )
            return {
                "success": True,
                "processed": 0,
                "failed": 0,
                "fetchedUnitCount": len(staged_units),
                "totalUnitCount": len(staged_units),
                "stoppedAt": first_staged_unit.source_unit_key,
                "outcome": "WAITING_REVIEW",
                "waitingForReview": True,
                "error": str(approval_exc),
                "errorCode": "configuration_approval_required",
                "rawStageKey": stage_key,
            }
        except Exception as exc:
            logger.warning(
                "Preflight mapping check failed for staged stream %s: %s",
                stage_key,
                exc,
            )

        if active_runtime_config is not None:
            await dependencies.create_stream_review_packet(
                database=context.db,
                partner=context.config.partner,
                file_type=FileType.SETTLEMENT,
                active_runtime_config=active_runtime_config,
                source_file_name=Path(first_staged_unit.local_path or "").name,
                source_file_path=first_staged_unit.local_path,
                reconciliation_date=context.reconciliation_date,
                raw_stage_key=stage_key,
                backfill_run_id=context.backfill_run_id,
            )
            review_checkpoint, won_review_claim = await checkpoint_repo.claim_unit(
                partner=identity["partner"],
                fetch_config_id=identity["fetchConfigId"],
                source_type=identity["sourceType"],
                stream_key=identity["streamKey"],
                unit_key=first_staged_unit.source_unit_key or "",
                mode=context.mode,
                cursor_before=first_staged_unit.cursor_before,
                expected_previous_unit_key=checkpoint.last_completed_unit_key
                if checkpoint
                else None,
                config_version=identity["configVersion"],
                source_endpoint=identity["sourceEndpoint"],
                stream_metadata={"page": first_staged_unit.page},
            )
            if won_review_claim:
                await checkpoint_repo.release_for_review(
                    review_checkpoint,
                    unit_key=first_staged_unit.source_unit_key or "",
                    reason="Complete paginated API stream awaits scope review.",
                )
            return {
                "success": True,
                "processed": 0,
                "failed": 0,
                "fetchedUnitCount": len(staged_units),
                "totalUnitCount": len(staged_units),
                "stoppedAt": first_staged_unit.source_unit_key,
                "outcome": "WAITING_REVIEW",
                "waitingForReview": True,
                "rawStageKey": stage_key,
            }

    result = await dependencies.process_source_units(
        checkpoint_repo,
        stream_identity={
            **identity,
            "lastCompletedUnitKey": checkpoint.last_completed_unit_key
            if checkpoint
            else None,
        },
        units=staged_units,
        ingest_unit=context.ingest_unit,
        mode=context.mode,
        retry_policy=retry_policy,
        on_unit_completed=mark_page_consumed,
    )
    result["fetchedUnitCount"] = len(staged_units)
    result["totalUnitCount"] = len(staged_units)
    return result


__all__ = ["run_paginated_stream", "resume_paginated_source_unit"]
