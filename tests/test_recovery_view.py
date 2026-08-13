"""Tests for the safe recovery read model exposed to operator views."""

from datetime import UTC, datetime, timedelta
from typing import Any

from src.application.ingestion.recovery_view import build_recovery_view
from src.domain.ingestion.checkpoints import (
    CheckpointStatus,
    IngestionCheckpoint,
    IngestionMode,
    SourceUnitStatus,
    SourceUnitSummary,
)
from src.domain.runtime.models import PartnerRuntimeRunStatus


def _checkpoint(**overrides: Any) -> IngestionCheckpoint:
    values: dict[str, Any] = {
        "partner": "VIETTELPAY",
        "fetch_config_id": "config-viettelpay",
        "source_type": "API",
        "stream_key": "VIETTELPAY:API:scheduled",
        "mode": IngestionMode.SCHEDULED,
    }
    values.update(overrides)
    return IngestionCheckpoint(**values)


def test_failed_recovery_view_contains_checkpoint_and_safe_timeline():
    retry_at = datetime.now(UTC) + timedelta(minutes=1)
    checkpoint = _checkpoint(
        status=CheckpointStatus.FAILED,
        current_unit_key="page:2",
        last_completed_unit_key="page:1",
        cursor_before="cursor-1",
        attempt_count=2,
        error_code="fetch_timeout",
        last_error="Gateway timeout while fetching page 2; token=secret-value",
        retryable=True,
        next_retry_at=retry_at,
        stream_metadata={"page": 2, "password": "must-not-leak"},
        unit_timeline=[
            SourceUnitSummary(
                unit_key="page:1",
                page=1,
                status=SourceUnitStatus.COMPLETED,
            ),
            SourceUnitSummary(
                unit_key="page:2",
                page=2,
                status=SourceUnitStatus.FAILED,
                attempt_count=2,
                error_code="fetch_timeout",
                last_error="Gateway timeout while fetching page 2",
                retryable=True,
                next_retry_at=retry_at,
            ),
        ],
    )

    view = build_recovery_view(
        checkpoint=checkpoint,
        latest_run={"status": "FAILED", "stats": {"duplicateRows": 0}},
        max_attempts=3,
    )

    assert view["status"] == "FAILED"
    assert view["lastCompletedUnitKey"] == "page:1"
    assert view["currentUnitKey"] == "page:2"
    assert view["currentPage"] == 2
    assert view["attemptCount"] == 2
    assert view["maxAttempts"] == 3
    assert view["retryable"] is True
    assert view["errorCode"] == "fetch_timeout"
    assert view["lastError"] == "Gateway timeout while fetching page 2; token=[REDACTED]"
    assert view["units"][1]["status"] == "FAILED"
    assert view["units"][1]["nextRetryAt"] == retry_at.isoformat()
    assert view["duplicateCount"] == 0
    assert "must-not-leak" not in str(view)


def test_recovery_view_redacts_sensitive_values_inside_unit_timeline():
    checkpoint = _checkpoint(
        status=CheckpointStatus.FAILED,
        current_unit_key="page:2",
        unit_timeline=[
            SourceUnitSummary(
                unit_key="page:2",
                status=SourceUnitStatus.FAILED,
                last_error="Authorization: Bearer unit-secret-value",
                error_code="fetch_timeout",
            )
        ],
    )

    view = build_recovery_view(
        checkpoint=checkpoint,
        latest_run={"status": "FAILED"},
        max_attempts=3,
    )

    assert "unit-secret-value" not in str(view)
    assert "REDACTED" in view["units"][0]["lastError"]


def test_recovery_view_hides_retry_after_operator_resolves_skip():
    checkpoint = _checkpoint(
        status=CheckpointStatus.DISCOVERED,
        current_unit_key="page:2",
        retryable=True,
        resolution_metadata={"action": "SKIP", "operatorId": "ops-user"},
        unit_timeline=[
            SourceUnitSummary(
                unit_key="page:2",
                status=SourceUnitStatus.PENDING,
            )
        ],
    )

    view = build_recovery_view(
        checkpoint=checkpoint,
        latest_run={"status": "FAILED"},
        max_attempts=3,
    )

    assert view["status"] == "PENDING"
    assert view["retryable"] is False


def test_recovery_view_prefers_persisted_retry_event_history():
    checkpoint = _checkpoint(
        status=CheckpointStatus.COMPLETED,
        unit_timeline=[
            SourceUnitSummary(
                unit_key="page:2",
                status=SourceUnitStatus.COMPLETED,
            )
        ],
        recovery_events=[
            {
                "eventId": "event-1",
                "unitKey": "page:2",
                "status": "PROCESSING",
                "timestamp": "2026-08-08T10:00:00+00:00",
            },
            {
                "eventId": "event-2",
                "unitKey": "page:2",
                "status": "FAILED",
                "timestamp": "2026-08-08T10:00:01+00:00",
                "errorCode": "fetch_timeout",
                "message": "Authorization: Bearer event-secret-value",
            },
            {
                "eventId": "event-3",
                "unitKey": "page:2",
                "status": "RETRY_REQUESTED",
                "timestamp": "2026-08-08T10:00:30+00:00",
                "action": "RETRY",
                "actor": "ops-user",
                "reason": "Operator requested immediate retry",
            },
            {
                "eventId": "event-4",
                "unitKey": "page:2",
                "status": "PROCESSING",
                "timestamp": "2026-08-08T10:01:00+00:00",
            },
            {
                "eventId": "event-5",
                "unitKey": "page:2",
                "status": "COMPLETED",
                "timestamp": "2026-08-08T10:01:01+00:00",
            },
        ],
    )

    view = build_recovery_view(
        checkpoint=checkpoint,
        latest_run={"status": "COMPLETED"},
        max_attempts=3,
    )

    assert [event["status"] for event in view["events"]] == [
        "PROCESSING",
        "FAILED",
        "RETRY_REQUESTED",
        "PROCESSING",
        "COMPLETED",
    ]
    assert "event-secret-value" not in str(view)


def test_waiting_review_is_not_mapped_to_failure():
    checkpoint = _checkpoint(
        status=CheckpointStatus.PROCESSING,
        current_unit_key=None,
        unit_timeline=[
            SourceUnitSummary(
                unit_key="file:pending-review",
                status=SourceUnitStatus.WAITING_REVIEW,
                error_code="configuration_approval_required",
            )
        ],
    )

    view = build_recovery_view(
        checkpoint=checkpoint,
        latest_run={"status": "WAITING_REVIEW"},
        max_attempts=3,
    )

    assert view["status"] == "WAITING_REVIEW"
    assert view["errorCode"] == "configuration_approval_required"
    assert view["retryable"] is None


def test_replay_is_distinguished_from_failure_without_checkpoint():
    view = build_recovery_view(
        checkpoint=None,
        latest_run={
            "status": "COMPLETED",
            "stats": {"outcome": "FETCH_UNIT_REPLAY"},
        },
        max_attempts=3,
    )

    assert view["status"] == "REPLAYED"
    assert view["safeDuplicate"] is True
    assert view["units"] == []


def test_recovery_view_normalizes_runtime_status_enum():
    view = build_recovery_view(
        checkpoint=None,
        latest_run={"status": PartnerRuntimeRunStatus.COMPLETED},
        max_attempts=3,
    )

    assert view["status"] == "COMPLETED"


def test_queued_runtime_is_processing_and_duplicate_count_is_safe():
    view = build_recovery_view(
        checkpoint=None,
        latest_run={
            "status": "QUEUED",
            "stats": {"duplicateRows": 4, "duplicates": 99},
        },
        max_attempts=3,
    )

    assert view["status"] == "PROCESSING"
    assert view["duplicateCount"] == 4


def test_recovery_view_keeps_retry_available_when_fetch_failed_before_checkpoint():
    view = build_recovery_view(
        checkpoint=None,
        latest_run={
            "status": "FAILED",
            "stats": {
                "errorCode": "fetch_http_5xx",
                "retryable": True,
                "fetchedUnitCount": 1,
                "totalUnitCount": 3,
            },
        },
        max_attempts=3,
        expected_unit_count=3,
    )

    assert view["status"] == "FAILED"
    assert view["retryable"] is True
    assert view["fetchedUnitCount"] == 1


def test_recovery_view_exposes_precheckpoint_runtime_attempt_events():
    view = build_recovery_view(
        checkpoint=None,
        latest_run={
            "status": "FAILED",
            "stats": {
                "errorCode": "fetch_http_5xx",
                "retryable": True,
                "fetchedUnitCount": 1,
                "totalUnitCount": 3,
                "currentPage": 2,
            },
            "attemptHistory": [
                {
                    "eventId": "attempt-1-failed",
                    "status": "FAILED",
                    "timestamp": "2026-08-10T00:00:01+00:00",
                    "errorCode": "fetch_http_5xx",
                    "message": "page 2 failed",
                }
            ],
        },
        max_attempts=3,
        expected_unit_count=3,
    )

    assert view["currentPage"] == 2
    assert [event["eventId"] for event in view["events"]] == ["attempt-1-failed"]


def test_recovery_view_merges_attempt_history_from_multiple_runtime_runs():
    view = build_recovery_view(
        checkpoint=None,
        latest_run={
            "status": "COMPLETED",
            "attemptHistory": [
                {
                    "eventId": "retry-runtime-started",
                    "status": "STARTED",
                    "timestamp": "2026-08-10T00:00:03+00:00",
                },
                {
                    "eventId": "retry-runtime-completed",
                    "status": "COMPLETED",
                    "timestamp": "2026-08-10T00:00:06+00:00",
                },
            ],
        },
        attempt_history=[
            {
                "eventId": "first-runtime-failed",
                "status": "FAILED",
                "timestamp": "2026-08-10T00:00:01+00:00",
            },
            {
                "eventId": "retry-requested",
                "status": "RETRY_REQUESTED",
                "timestamp": "2026-08-10T00:00:02+00:00",
            },
        ],
        max_attempts=3,
    )

    assert [event["eventId"] for event in view["events"]] == [
        "first-runtime-failed",
        "retry-requested",
        "retry-runtime-started",
        "retry-runtime-completed",
    ]
    assert view["requestAttemptCount"] == 2
    assert [event["requestAttempt"] for event in view["events"]] == [1, 2, 2, 2]


def test_recovery_view_numbers_first_request_and_manual_retry():
    view = build_recovery_view(
        checkpoint=None,
        latest_run={
            "status": "COMPLETED",
            "attemptHistory": [
                {
                    "eventId": "request-1-started",
                    "status": "STARTED",
                    "attempt": 1,
                    "timestamp": "2026-08-11T00:00:01+00:00",
                },
                {
                    "eventId": "request-1-failed",
                    "status": "FAILED",
                    "attempt": 1,
                    "timestamp": "2026-08-11T00:00:02+00:00",
                },
                {
                    "eventId": "request-2-started",
                    "status": "STARTED",
                    "attempt": 2,
                    "timestamp": "2026-08-11T00:00:03+00:00",
                },
            ],
        },
        max_attempts=3,
    )

    assert view["requestAttemptCount"] == 2
    assert [event["requestAttempt"] for event in view["events"]] == [1, 1, 2]


def test_recovery_view_uses_expected_api_unit_count_before_all_pages_are_discovered():
    checkpoint = _checkpoint(
        status=CheckpointStatus.FAILED,
        current_unit_key="page:2",
        last_completed_unit_key="page:1",
        unit_timeline=[
            SourceUnitSummary(unit_key="page:1", page=1, status=SourceUnitStatus.COMPLETED),
            SourceUnitSummary(unit_key="page:2", page=2, status=SourceUnitStatus.FAILED),
        ],
    )

    view = build_recovery_view(
        checkpoint=checkpoint,
        latest_run={"status": "FAILED"},
        max_attempts=3,
        expected_unit_count=3,
    )

    assert view["completedUnitCount"] == 1
    assert view["totalUnitCount"] == 3
    assert len(view["units"]) == 2


def test_recovery_view_exposes_fetched_units_separately_from_ingested_units():
    checkpoint = _checkpoint(
        status=CheckpointStatus.DISCOVERED,
        unit_timeline=[
            SourceUnitSummary(
                unit_key="page:1",
                page=1,
                status=SourceUnitStatus.WAITING_REVIEW,
            )
        ],
    )

    view = build_recovery_view(
        checkpoint=checkpoint,
        latest_run={
            "status": "WAITING_REVIEW",
            "stats": {"fetchedUnitCount": 3, "totalUnitCount": 3},
        },
        max_attempts=3,
        expected_unit_count=3,
    )

    assert view["fetchedUnitCount"] == 3
    assert view["completedUnitCount"] == 0
    assert view["totalUnitCount"] == 3


def test_recovery_view_builds_safe_event_timeline_and_resolution_event():
    started = datetime.now(UTC) - timedelta(minutes=2)
    completed = datetime.now(UTC) - timedelta(minutes=1)
    resolved = datetime.now(UTC) + timedelta(seconds=1)
    checkpoint = _checkpoint(
        status=CheckpointStatus.BLOCKED,
        current_unit_key="page:2",
        resolution_metadata={
            "action": "SKIP",
            "operatorId": "ops-user",
            "reason": "Skip after token=private-value review",
            "resolvedAt": resolved,
        },
        unit_timeline=[
            SourceUnitSummary(
                unit_key="page:1",
                status=SourceUnitStatus.COMPLETED,
                started_at=started,
                completed_at=completed,
            ),
            SourceUnitSummary(
                unit_key="page:2",
                status=SourceUnitStatus.BLOCKED,
                last_error="terminal source failure",
                error_code="pagination_parse_error",
            ),
        ],
    )

    view = build_recovery_view(checkpoint=checkpoint, latest_run=None, max_attempts=3)

    assert [event["status"] for event in view["events"]] == [
        "PROCESSING",
        "COMPLETED",
        "BLOCKED",
        "RESOLVED",
    ]
    resolution = view["events"][-1]
    assert resolution["actor"] == "ops-user"
    assert resolution["action"] == "SKIP"
    assert "private-value" not in str(view)
