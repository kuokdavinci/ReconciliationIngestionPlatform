"""Sequential source-unit orchestration for scheduled and backfill streams."""

from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from src.domain.ingestion.checkpoints import CheckpointRepository, IngestionMode
from src.domain.ingestion.source_units import IngestionOutcome, SourceUnitMetadata
from src.services.retry_policy import RetryPolicy


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
            stream_metadata=stream_identity.get("streamMetadata") or {},
        )

        if not won_claim:
            if checkpoint.last_completed_unit_key == unit_key:
                replayed += 1
                previous_unit_key = unit_key
                continue
            return {
                "success": False,
                "processed": processed,
                "failed": failed + 1,
                "stoppedAt": unit_key,
                "error": "Source unit claim was not acquired",
            }

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
            advanced = completed and await checkpoint_repo.advance(
                checkpoint, unit_key=unit_key
            )
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
            continue

        ingestion_result = await ingest_unit(unit)
        raw_outcome = (
            ingestion_result.get("outcome")
            if isinstance(ingestion_result, Mapping)
            else getattr(ingestion_result, "outcome", None)
        )
        if raw_outcome in {"FILE_DUPLICATE", "FETCH_UNIT_REPLAY"}:
            duplicate_outcomes.append(raw_outcome)
        outcome = IngestionOutcome.from_result(ingestion_result)
        if outcome.waiting_for_review:
            released = await checkpoint_repo.release_for_review(
                checkpoint,
                unit_key=unit_key,
                reason=outcome.error,
            )
            if not released:
                return {
                    "success": False,
                    "processed": processed,
                    "failed": failed + 1,
                    "stoppedAt": unit_key,
                    "error": "Checkpoint release for review failed",
                }
            return {
                "success": True,
                "processed": processed,
                "failed": failed,
                "stoppedAt": unit_key,
                "outcome": "WAITING_REVIEW",
                "waitingForReview": True,
                "error": outcome.error,
            }
        if not outcome.success:
            failure_max_attempts = max_attempts
            failure_next_retry_at = outcome.next_retry_at
            failure_retryable = outcome.retryable
            if retry_policy is not None and outcome.retryable:
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
                error=outcome.error,
                error_code=outcome.error_code,
                retryable=failure_retryable,
                next_retry_at=failure_next_retry_at,
                max_attempts=failure_max_attempts,
                error_metadata=outcome.error_metadata,
            )
            return {
                "success": False,
                "processed": processed,
                "failed": failed + 1,
                "stoppedAt": unit_key,
                "error": outcome.error,
            }

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
            return {
                "success": False,
                "processed": processed,
                "failed": failed + 1,
                "stoppedAt": unit_key,
                "error": error,
            }

        advanced = await checkpoint_repo.advance(checkpoint, unit_key=unit_key)
        if not advanced:
            return {
                "success": False,
                "processed": processed,
                "failed": failed + 1,
                "stoppedAt": unit_key,
                "error": "Checkpoint advance update failed",
            }
        if on_unit_completed is not None:
            await on_unit_completed(unit)
        previous_unit_key = unit_key
        processed += 1

    result: dict[str, Any] = {
        "success": failed == 0,
        "processed": processed,
        "failed": failed,
    }
    if replayed:
        result["replayed"] = replayed
    if skipped:
        result["skipped"] = skipped
    if duplicate_outcomes and len(duplicate_outcomes) == processed:
        result["outcome"] = (
            duplicate_outcomes[0]
            if len(set(duplicate_outcomes)) == 1
            else "FETCH_UNIT_REPLAY"
        )
        result["reconciliationSkipped"] = True
    return result
