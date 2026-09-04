"""Sequential source-unit orchestration for scheduled and backfill streams."""

from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from src.domain.ingestion.checkpoints import CheckpointRepository, IngestionMode
from src.domain.ingestion.source_units import IngestionOutcome, SourceUnitMetadata
from src.domain.ingestion.retry_policy import RetryPolicy
from src.core.utils import sanitize_runtime_error


async def process_source_units(
    checkpoint_repo: CheckpointRepository,
    *,
    stream_identity: dict[str, Any],
    units: Iterable[SourceUnitMetadata | dict[str, Any]],
    ingest_unit: Callable[[SourceUnitMetadata], Awaitable[Any]],
    mode: IngestionMode = IngestionMode.SCHEDULED,
    max_attempts: int | None = None,
    retry_policy: RetryPolicy | None = None,
    on_unit_completed: Callable[[SourceUnitMetadata], Awaitable[None]] | None = None,
    on_unit_observed: Callable[[SourceUnitMetadata, Any, Any], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Process source units in order and stop at the first failed unit.

    The checkpoint is the sequencing boundary: a unit is claimed before
    ingestion and advanced only after ingestion succeeds.  A unit already
    recorded as the last completed unit is treated as a replay-safe outcome.
    """

    processed = 0
    failed = 0
    replayed = 0
    skipped = 0
    partial_outcome = False
    duplicate_outcomes: list[str] = []
    previous_unit_key = stream_identity.get("lastCompletedUnitKey")
    attempt_limit = retry_policy.max_attempts if retry_policy else max_attempts

    for raw_unit in units:
        unit = SourceUnitMetadata.from_payload(raw_unit)
        unit_key = unit.source_unit_key
        if not unit_key:
            return {
                "success": False,
                "processed": processed,
                "failed": failed + 1,
                "stoppedAt": None,
                "error": "Source unit is missing sourceUnitKey",
            }

        checkpoint, won_claim = await checkpoint_repo.claim_unit(
            partner=stream_identity["partner"],
            fetch_config_id=stream_identity["fetchConfigId"],
            source_type=stream_identity["sourceType"],
            stream_key=stream_identity["streamKey"],
            unit_key=unit_key,
            mode=mode,
            cursor_before=unit.cursor_before,
            expected_previous_unit_key=previous_unit_key,
            max_attempts=attempt_limit,
            config_version=stream_identity.get("configVersion"),
            source_endpoint=stream_identity.get("sourceEndpoint"),
            stream_metadata={
                **(stream_identity.get("streamMetadata") or {}),
                "page": unit.page,
            },
            runtime_run_id=stream_identity.get("runtimeRunId"),
            source_file_id=stream_identity.get("sourceFileId"),
            attempt=stream_identity.get("attempt"),
        )

        if not won_claim:
            if checkpoint.last_completed_unit_key == unit_key:
                replayed += 1
                previous_unit_key = unit_key
                if on_unit_observed is not None:
                    try:
                        await on_unit_observed(
                            unit,
                            {
                                "success": True,
                                "outcome": "FETCH_UNIT_REPLAY",
                                "replayed": True,
                            },
                            checkpoint,
                        )
                    except Exception:
                        pass
                continue
            return {
                "success": False,
                "processed": processed,
                "failed": failed + 1,
                "stoppedAt": unit_key,
                "error": "Source unit claim was not acquired",
                "errorCode": "source_unit_claim_not_acquired",
                "claim": {
                    "expectedPreviousUnitKey": previous_unit_key,
                    "lastCompletedUnitKey": checkpoint.last_completed_unit_key,
                    "currentUnitKey": checkpoint.current_unit_key,
                    "status": getattr(checkpoint.status, "value", checkpoint.status),
                    "attemptCount": checkpoint.attempt_count,
                },
            }

        if on_unit_observed is not None:
            try:
                await on_unit_observed(unit, {"outcome": "CLAIMED"}, checkpoint)
            except Exception:
                pass

        resolution_metadata = getattr(checkpoint, "resolution_metadata", {})
        if (
            isinstance(resolution_metadata, dict)
            and resolution_metadata.get("action") == "SKIP"
            and checkpoint.current_unit_key == unit_key
        ):
            completed = await checkpoint_repo.mark_completed(
                checkpoint,
                unit_key=unit_key,
                cursor_after=unit.cursor_after,
                high_water_mark=unit.high_water_mark,
            )
            advanced = completed and await checkpoint_repo.advance(checkpoint, unit_key=unit_key)
            if not advanced:
                return {
                    "success": False,
                    "processed": processed,
                    "failed": failed + 1,
                    "stoppedAt": unit_key,
                    "error": "Checkpoint skip advancement failed",
                }
            skipped += 1
            previous_unit_key = unit_key
            if on_unit_observed is not None:
                try:
                    await on_unit_observed(
                        unit,
                        {
                            "success": True,
                            "outcome": "FETCH_UNIT_REPLAY",
                            "skipped": True,
                        },
                        checkpoint,
                    )
                except Exception:
                    pass
            continue

        try:
            ingestion_result = await ingest_unit(unit)
        except Exception as exc:
            # A worker exception must not leave the checkpoint in PROCESSING.
            # Airflow may retry the same runtime immediately, and a live claim
            # would otherwise make that retry look like a second concurrent
            # run ("claim was not acquired") until the stale-claim timeout.
            error = sanitize_runtime_error(exc)
            await checkpoint_repo.mark_failed(
                checkpoint,
                unit_key=unit_key,
                error=error,
                error_code="source_runtime_error",
                retryable=True,
                next_retry_at=None,
                max_attempts=attempt_limit,
                error_metadata={"exceptionType": exc.__class__.__name__},
            )
            if on_unit_observed is not None:
                try:
                    await on_unit_observed(
                        unit,
                        {
                            "success": False,
                            "outcome": "FAILED",
                            "error": error,
                            "errorCode": "source_runtime_error",
                        },
                        checkpoint,
                    )
                except Exception:
                    pass
            raise
        raw_outcome = (
            ingestion_result.get("outcome")
            if isinstance(ingestion_result, Mapping)
            else getattr(ingestion_result, "outcome", None)
        )
        source_file_id = (
            ingestion_result.get("sourceFileId")
            if isinstance(ingestion_result, Mapping)
            else None
        )
        update_source_context = getattr(checkpoint_repo, "update_source_context", None)
        if source_file_id is not None and callable(update_source_context):
            try:
                await update_source_context(
                    checkpoint,
                    source_file_id=str(source_file_id),
                    runtime_run_id=stream_identity.get("runtimeRunId"),
                )
            except Exception:
                pass
        if raw_outcome in {"FILE_DUPLICATE", "FETCH_UNIT_REPLAY"}:
            duplicate_outcomes.append(raw_outcome)
        outcome = IngestionOutcome.from_result(ingestion_result)
        if outcome.waiting_for_review:
            review_reason = sanitize_runtime_error(outcome.error)
            released = await checkpoint_repo.release_for_review(
                checkpoint,
                unit_key=unit_key,
                reason=review_reason,
            )
            if not released:
                return {
                    "success": False,
                    "processed": processed,
                    "failed": failed + 1,
                    "stoppedAt": unit_key,
                    "error": "Checkpoint release for review failed",
                }
            result = {
                "success": True,
                "processed": processed,
                "failed": failed,
                "stoppedAt": unit_key,
                "outcome": "WAITING_REVIEW",
                "waitingForReview": True,
                "error": review_reason,
            }
            if outcome.quality_decision is not None:
                result.update(
                    {
                        "qualityDecision": outcome.quality_decision,
                        "orchestrationAction": outcome.orchestration_action,
                        "qualityCounters": dict(outcome.quality_counters),
                        "topRuleCodes": list(outcome.top_rule_codes[:10]),
                    }
                )
            if on_unit_observed is not None:
                try:
                    await on_unit_observed(
                        unit,
                        {
                            **result,
                            "errorCode": getattr(
                                ingestion_result, "error_code", None
                            )
                            if not isinstance(ingestion_result, Mapping)
                            else ingestion_result.get("errorCode"),
                        },
                        checkpoint,
                    )
                except Exception:
                    pass
            return result
        if not outcome.success:
            quality_failure = outcome.orchestration_action == "FAIL"
            failure_max_attempts = max_attempts
            failure_next_retry_at = outcome.next_retry_at
            failure_retryable = outcome.retryable
            if quality_failure:
                failure_retryable = False
                failure_next_retry_at = None
                failure_max_attempts = None
            if retry_policy is not None and outcome.retryable and not quality_failure:
                if retry_policy.classify(outcome.error_code).value == "TERMINAL":
                    failure_retryable = False
                    failure_next_retry_at = None
                else:
                    failure_max_attempts = retry_policy.max_attempts
                    failure_next_retry_at = retry_policy.next_retry_at(
                        outcome.error_code,
                        checkpoint.attempt_count,
                        now=datetime.now(UTC),
                    )
            await checkpoint_repo.mark_failed(
                checkpoint,
                unit_key=unit_key,
                error=sanitize_runtime_error(outcome.error),
                error_code=sanitize_runtime_error(outcome.error_code, max_length=96),
                retryable=failure_retryable,
                next_retry_at=failure_next_retry_at,
                max_attempts=failure_max_attempts,
                error_metadata=outcome.error_metadata,
            )
            result = {
                "success": False,
                "processed": processed,
                "failed": failed + 1,
                "stoppedAt": unit_key,
                "error": sanitize_runtime_error(outcome.error),
            }
            if outcome.quality_decision is not None:
                result.update(
                    {
                        "qualityDecision": outcome.quality_decision,
                        "orchestrationAction": outcome.orchestration_action,
                        "qualityCounters": dict(outcome.quality_counters),
                        "topRuleCodes": list(outcome.top_rule_codes[:10]),
                    }
                )
            if on_unit_observed is not None:
                try:
                    await on_unit_observed(
                        unit,
                        {
                            **result,
                            "errorCode": sanitize_runtime_error(
                                outcome.error_code, max_length=96
                            ),
                        },
                        checkpoint,
                    )
                except Exception:
                    pass
            return result
        partial_outcome = partial_outcome or raw_outcome == "PARTIAL"

        completed = await checkpoint_repo.mark_completed(
            checkpoint,
            unit_key=unit_key,
            cursor_after=unit.cursor_after,
            high_water_mark=unit.high_water_mark,
        )
        if not completed:
            error = "Checkpoint completion update failed"
            await checkpoint_repo.mark_failed(
                checkpoint,
                unit_key=unit_key,
                error=error,
                error_code="checkpoint_advance_error",
                retryable=True,
                next_retry_at=None,
                max_attempts=max_attempts,
                error_metadata={},
            )
            if on_unit_observed is not None:
                try:
                    await on_unit_observed(
                        unit,
                        {
                            "success": False,
                            "processed": processed,
                            "failed": failed + 1,
                            "stoppedAt": unit_key,
                            "error": error,
                            "errorCode": "checkpoint_advance_error",
                        },
                        checkpoint,
                    )
                except Exception:
                    pass
            return {
                "success": False,
                "processed": processed,
                "failed": failed + 1,
                "stoppedAt": unit_key,
                "error": error,
            }

        advanced = await checkpoint_repo.advance(checkpoint, unit_key=unit_key)
        if not advanced:
            error = "Checkpoint advance update failed"
            if on_unit_observed is not None:
                try:
                    await on_unit_observed(
                        unit,
                        {
                            "success": False,
                            "processed": processed,
                            "failed": failed + 1,
                            "stoppedAt": unit_key,
                            "error": error,
                            "errorCode": "checkpoint_advance_error",
                        },
                        checkpoint,
                    )
                except Exception:
                    pass
            return {
                "success": False,
                "processed": processed,
                "failed": failed + 1,
                "stoppedAt": unit_key,
                "error": "Checkpoint advance update failed",
            }
        if on_unit_observed is not None:
            try:
                await on_unit_observed(unit, ingestion_result, checkpoint)
            except Exception:
                pass
        if on_unit_completed is not None:
            await on_unit_completed(unit)
        previous_unit_key = unit_key
        processed += 1

    summary_result: dict[str, Any] = {
        "success": failed == 0,
        "processed": processed,
        "failed": failed,
    }
    if replayed:
        summary_result["replayed"] = replayed
    if skipped:
        summary_result["skipped"] = skipped
    if duplicate_outcomes and len(duplicate_outcomes) == processed:
        summary_result["outcome"] = (
            duplicate_outcomes[0] if len(set(duplicate_outcomes)) == 1 else "FETCH_UNIT_REPLAY"
        )
        summary_result["reconciliationSkipped"] = True
    elif partial_outcome:
        summary_result["outcome"] = "PARTIAL"
    return summary_result


async def resume_held_source_unit(
    checkpoint_repo: CheckpointRepository,
    quarantine_repo: Any,
    *,
    source_unit_key: str,
    stream_identity: dict[str, Any],
    unit: SourceUnitMetadata | dict[str, Any],
    ingest_unit: Callable[[SourceUnitMetadata], Awaitable[Any]],
    mode: IngestionMode = IngestionMode.SCHEDULED,
    max_attempts: int | None = None,
    retry_policy: RetryPolicy | None = None,
    on_unit_completed: Callable[[SourceUnitMetadata], Awaitable[None]] | None = None,
    on_unit_observed: Callable[[SourceUnitMetadata, Any, Any], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Resume one held unit through the existing checkpoint state machine.

    The blocker guard runs before checkpoint claim. ``process_source_units``
    advances the checkpoint before invoking ``on_unit_completed``; callers can
    therefore consume staged payloads or clean local files only after commit.
    """
    requested = SourceUnitMetadata.from_payload(unit)
    if requested.source_unit_key != source_unit_key:
        raise ValueError("sourceUnitKey does not match the source unit payload")
    if await quarantine_repo.has_unresolved_blockers(source_unit_key):
        return {
            "success": False,
            "processed": 0,
            "failed": 1,
            "stoppedAt": source_unit_key,
            "outcome": "QUARANTINE_BLOCKED",
            "errorCode": "quarantine_conflict_unresolved",
            "error": "Source unit has unresolved conflicting duplicate quarantine records.",
        }
    return await process_source_units(
        checkpoint_repo,
        stream_identity={
            **stream_identity,
            "lastCompletedUnitKey": stream_identity.get("lastCompletedUnitKey"),
        },
        units=[requested],
        ingest_unit=ingest_unit,
        mode=mode,
        max_attempts=max_attempts,
        retry_policy=retry_policy,
        on_unit_completed=on_unit_completed,
        on_unit_observed=on_unit_observed,
    )
