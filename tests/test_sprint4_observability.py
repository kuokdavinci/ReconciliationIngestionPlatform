"""Focused contracts for Sprint 4 runtime observability."""

import json
import logging
from io import StringIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application.automation.stream_runtime import finish_source_stream_run
from src.application.automation.job_queries import AutomationJobQueryService
from src.application.ingestion.source_unit_orchestrator import process_source_units
from src.application.runtime.service import serialize_partner_runtime_run, update_runtime_run
from src.domain.ingestion.checkpoints import IngestionCheckpoint
from src.domain.ingestion.source_units import SourceUnitMetadata
from src.domain.runtime.models import (
    PartnerRuntimeRun,
    PartnerRuntimeRunStatus,
    PartnerRuntimeTriggerType,
    RuntimeOrchestrationContext,
)
from src.logging.logger import JSONFormatter, StructuredLogger
from src.pipeline.observability import IngestionStage
from src.pipeline.metrics import IngestionPerformance
from src.pipeline.row_batch_coordinator import RowBatchMetrics
from src.pipeline.run_state import IngestionRunState
from src.domain.partner_transaction.duplicates import BatchWriteResult
from src.pipeline.finalizer import IngestionRunFinalizer


def test_stage_summary_has_nonnegative_accumulated_durations_and_row_invariant() -> None:
    state = IngestionRunState(
        run_id="runtime-1",
        partner="MOMO",
        attempt=2,
    )
    state.set_source_context(
        source_file_id="file-1",
        source_unit_key="unit-001",
        page=1,
        checkpoint_before={"status": "PROCESSING", "cursorBefore": "c-0"},
    )
    state.begin_stage(IngestionStage.READING.value)
    state.finish_stage()
    state.begin_stage(IngestionStage.PROCESSING.value)
    state.finish_stage()
    processing_once = state.stage_durations_ms[IngestionStage.PROCESSING.value]
    state.begin_stage(IngestionStage.PROCESSING.value)
    state.finish_stage()
    processing_twice = state.stage_durations_ms[IngestionStage.PROCESSING.value]
    state.total_rows = 100
    state.success_rows = 95
    state.rejected_rows = 3
    state.duplicate_rows = 1
    state.persistence_failed_rows = 1
    state.quarantined_rows = 3
    state.set_source_context(checkpoint_after={"status": "COMPLETED", "cursorAfter": "c-1"})
    state.finish_run()

    summary = state.stage_summary
    assert set(summary["stageDurationsMs"]) == {"READING", "PROCESSING"}
    assert all(duration >= 0 for duration in summary["stageDurationsMs"].values())
    assert summary["stageDurationsMs"]["PROCESSING"] == processing_twice
    assert processing_twice >= processing_once
    assert summary["durationMs"] >= 0
    assert summary["inputRows"] == (
        summary["persistedRows"]
        + summary["rejectedRows"]
        + summary["duplicateRows"]
        + summary["persistenceFailedRows"]
    )
    assert summary["quarantinedRows"] <= summary["rejectedRows"]
    assert summary["currentUnitKey"] == "unit-001"
    assert summary["checkpointBefore"]["cursorBefore"] == "c-0"
    assert summary["checkpointAfter"]["cursorAfter"] == "c-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "expected_status"),
    [
        ({"success": True, "outcome": "INGESTED"}, PartnerRuntimeRunStatus.COMPLETED),
        (
            {
                "success": True,
                "outcome": "PARTIAL",
                "stageSummary": {"rejectedRows": 2},
            },
            PartnerRuntimeRunStatus.PARTIAL,
        ),
        (
            {"success": False, "errorCode": "batch_fatal", "error": "fatal"},
            PartnerRuntimeRunStatus.FAILED,
        ),
        (
            {
                "success": True,
                "outcome": "WAITING_REVIEW",
                "waitingForReview": True,
            },
            PartnerRuntimeRunStatus.WAITING_REVIEW,
        ),
        (
            {"success": True, "outcome": "SAFE_DUPLICATE", "safeDuplicate": True},
            PartnerRuntimeRunStatus.COMPLETED,
        ),
    ],
)
async def test_runtime_status_matrix(result, expected_status) -> None:
    run = SimpleNamespace(
        id="runtime-1",
        orchestration=RuntimeOrchestrationContext(
            dagId="dag-1",
            dagRunId="dag-run-1",
            taskId="task-1",
            tryNumber=3,
        ),
    )
    with patch(
        "src.application.automation.stream_runtime.update_runtime_run",
        new=AsyncMock(),
    ) as persist:
        stats = {
            "totalRows": 10,
            "successRows": 10,
            "duplicateRows": 1 if result.get("safeDuplicate") else 0,
            "rejectedRows": 0,
            "persistenceFailedRows": 0,
            "quarantinedRows": 0,
        }
        stage_summary = {"durationMs": 1.0}
        if result.get("outcome") == "PARTIAL":
            stage_summary["rejectedRows"] = 2
        finished = await finish_source_stream_run(
            db=MagicMock(),
            run=run,
            partner="MOMO",
            result=result,
            stats=stats,
            stage_summary=stage_summary,
        )

    assert persist.await_args.kwargs["status"] is expected_status
    assert persist.await_args.kwargs["stage_summary"]["finishedAt"]
    assert persist.await_args.kwargs["attempt_event"]["attempt"] == 3
    assert finished["runtimeRun"]["status"] == expected_status.value


def test_ingestion_stage_log_schema_redacts_and_bounds_error() -> None:
    logger = StructuredLogger(name="sprint4-stage-schema")
    logger._logger.setLevel(logging.INFO)
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    logger._logger.handlers = [handler]

    logger.emit_ingestion_stage(
        IngestionStage.PERSISTING.value,
        "runtime-1",
        source_file_id=None,
        error_code="source_persist_error",
        partner="MOMO",
        source_unit_key="unit-001",
        page=2,
        attempt=4,
        checkpoint_before={"cursor": "before"},
        checkpoint_after=None,
        error="password=top-secret " + ("x" * 400),
    )

    event = json.loads(stream.getvalue())
    assert event["event"] == "INGESTION_STAGE"
    assert event["timestamp"]
    assert event["run_id"] == "runtime-1"
    assert event["partner"] == "MOMO"
    assert event["stage"] == "PERSISTING"
    assert event["attempt"] == 4
    assert event["source_file_id"] is None
    assert event["checkpoint_after"] is None
    assert "top-secret" not in event["error"]
    assert len(event["error"]) <= 259


def test_runtime_serialization_defaults_legacy_stage_summary_to_empty() -> None:
    run = PartnerRuntimeRun(
        partner="MOMO",
        date="2026-09-03",
        triggerType=PartnerRuntimeTriggerType.SCHEDULER,
        status=PartnerRuntimeRunStatus.COMPLETED,
        stageSummary={"currentStage": "FINALIZING"},
    )
    assert serialize_partner_runtime_run(run)["stageSummary"] == {
        "currentStage": "FINALIZING"
    }

    from src.infrastructure.runtime.repository import PartnerRuntimeRunRepository

    legacy = PartnerRuntimeRunRepository(MagicMock())._from_mongo(
        {
            "_id": "legacy-runtime",
            "partner": "MOMO",
            "date": "2026-09-03",
            "triggerType": "SCHEDULER",
            "status": "COMPLETED",
        }
    )
    assert legacy.stage_summary == {}


@pytest.mark.asyncio
async def test_runtime_update_uses_set_for_summary_and_push_for_attempt() -> None:
    repository = MagicMock()
    repository.update_fields = AsyncMock()
    with patch(
        "src.application.runtime.service.PartnerRuntimeRunRepository",
        return_value=repository,
    ):
        await update_runtime_run(
            MagicMock(),
            "runtime-1",
            stage_summary={"currentStage": "READING"},
            attempt_event={"stage": "READING", "attempt": 1},
        )

    repository.update_fields.assert_awaited_once()
    fields = repository.update_fields.await_args.args[1]
    assert fields["stageSummary"] == {"currentStage": "READING"}
    assert repository.update_fields.await_args.kwargs["attempt_event"]["stage"] == "READING"


@pytest.mark.asyncio
async def test_jobs_projection_exposes_stage_summary_in_latest_and_recent_runs() -> None:
    config = SimpleNamespace(
        enabled=True,
        partner="MOMO",
        id="fetch-1",
        updated_at="2026-09-03T00:00:00+00:00",
        fetch_method=SimpleNamespace(value="API"),
        schedule="0 0 * * *",
        local_download_dir=None,
        get_method_config=lambda: None,
    )
    run = PartnerRuntimeRun(
        partner="MOMO",
        date="2026-09-03",
        triggerType=PartnerRuntimeTriggerType.SCHEDULER,
        status=PartnerRuntimeRunStatus.COMPLETED,
        stageSummary={"currentStage": "FINALIZING", "durationMs": 12.0},
    )
    db = MagicMock()
    db["reconciliation_file"].find_one = AsyncMock(return_value=None)
    service = AutomationJobQueryService(
        db=db,
        fetch_repo=SimpleNamespace(find_enabled=AsyncMock(return_value=[config])),
        packet_repo=SimpleNamespace(find_many=AsyncMock(return_value=[])),
        runtime_run_repo=SimpleNamespace(
            find_latest_by_partner=AsyncMock(return_value=run),
            find_recent_by_partner=AsyncMock(return_value=[run]),
        ),
        checkpoint_repo=SimpleNamespace(find_by_streams=AsyncMock(return_value=[])),
        backfill_repo=SimpleNamespace(
            find_latest_active_by_partner=AsyncMock(return_value=None)
        ),
    )

    job = (await service.list_jobs())[0]

    assert job["latestRuntimeRun"]["stageSummary"]["currentStage"] == "FINALIZING"
    assert job["recentRuntimeRuns"][0]["stageSummary"]["durationMs"] == 12.0


@pytest.mark.asyncio
async def test_source_unit_claim_propagates_runtime_context_and_observes_completion() -> None:
    checkpoint = IngestionCheckpoint(
        partner="MOMO",
        fetchConfigId="fetch-1",
        sourceType="API",
        streamKey="stream-1",
    )
    repository = MagicMock()
    repository.claim_unit = AsyncMock(return_value=(checkpoint, True))
    repository.mark_completed = AsyncMock(return_value=True)
    repository.advance = AsyncMock(return_value=True)
    repository.update_source_context = AsyncMock(return_value=True)
    observed = []

    async def ingest(unit: SourceUnitMetadata) -> dict:
        return {
            "success": True,
            "outcome": "PARTIAL",
            "sourceFileId": "file-1",
            "stageSummary": {"currentStage": "FINALIZING", "rejectedRows": 1},
        }

    result = await process_source_units(
        repository,
        stream_identity={
            "partner": "MOMO",
            "fetchConfigId": "fetch-1",
            "sourceType": "API",
            "streamKey": "stream-1",
            "runtimeRunId": "runtime-1",
            "sourceFileId": "file-1",
            "attempt": 2,
        },
        units=[
            SourceUnitMetadata(
                sourceUnitKey="unit-001",
                page=1,
                cursorBefore="c-0",
                cursorAfter="c-1",
            )
        ],
        ingest_unit=ingest,
        on_unit_observed=lambda unit, value, current: _observe(observed, value),
    )

    kwargs = repository.claim_unit.await_args.kwargs
    assert kwargs["runtime_run_id"] == "runtime-1"
    assert kwargs["source_file_id"] == "file-1"
    assert kwargs["attempt"] == 2
    assert repository.update_source_context.await_args.kwargs["source_file_id"] == "file-1"
    assert result["success"] is True
    assert len(observed) == 2


async def _observe(observed: list, value: object) -> None:
    observed.append(value)


def test_batch_metrics_append_sql_components_without_changing_legacy_fields() -> None:
    metrics = RowBatchMetrics()
    metrics.parse_rows_ms = 5.0
    metrics.normalize_ms = 6.0
    metrics.validate_ms = 7.0
    metrics.record_batch_result(
        BatchWriteResult(
            inserted=2,
            timings_ms={
                "batch_wall_ms": 12.0,
                "mapping_ms": 2.0,
                "copy_ms": 3.0,
                "insert_classify_ms": 4.0,
                "transaction_overhead_ms": 1.0,
            },
        )
    )

    assert metrics.db_insert_ms == 0.0
    assert metrics.as_dict()["parseRowsMs"] == 5.0
    assert metrics.as_dict()["normalizeMs"] == 6.0
    assert metrics.as_dict()["validateMs"] == 7.0
    assert metrics.as_dict()["totalBatchWallMs"] == 12.0
    assert metrics.as_dict()["copyMs"] == 3.0
    assert metrics.as_dict()["insertClassifyMs"] == 4.0
    state = IngestionRunState()
    state.record_batch_metrics(metrics.as_dict())
    assert state.stage_summary["batchMetrics"]["parseRowsMs"] == 5.0
    assert state.stage_summary["batchMetrics"]["normalizeMs"] == 6.0
    assert state.stage_summary["batchMetrics"]["validateMs"] == 7.0


def test_error_samples_are_bounded_but_error_counter_is_exact() -> None:
    state = IngestionRunState()
    for row in range(20):
        state.record_invalid_row([{"field": "amount", "row": row}])

    assert len(state.errors) == 5
    assert state.error_count == 20
    assert state.error_samples_dropped == 15
    assert state.quality_counters["failedRows"] == 0


def test_performance_log_appends_named_component_metrics() -> None:
    line = IngestionPerformance(
        total_ingest_ms=10,
        read_file_ms=1,
        parse_rows_ms=2,
        normalize_ms=3,
        validate_ms=1,
        db_insert_ms=2,
        post_insert_update_ms=1,
        records_count=10,
        batch_size=5,
        db_write_operation_count=2,
        error_count=0,
        slowest_batch_ms=2,
        wall_clock_ms=10,
        total_batch_wall_ms=8,
        persistence_window_ms=7,
        mapping_ms=1,
        copy_ms=2,
        insert_classify_ms=3,
        transaction_overhead_ms=1,
    ).to_log_line()

    assert "wall_clock_ms=10.00" in line
    assert "insert_classify_ms=3.00" in line
    assert "transaction_overhead_ms=1.00" in line


def test_observability_write_warning_is_structured_and_bounded() -> None:
    logger = StructuredLogger(name="sprint4-observability-write-warning")
    logger._logger.setLevel(logging.WARNING)
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    logger._logger.handlers = [handler]

    logger.emit_ingestion_observability_write_failed(
        run_id="runtime-1",
        source_file_id="file-1",
        partner="MOMO",
        stage="PERSISTING",
    )

    event = json.loads(stream.getvalue())
    assert event["level"] == "WARNING"
    assert event["event"] == "INGESTION_OBSERVABILITY_WRITE_FAILED"
    assert event["run_id"] == "runtime-1"
    assert event["source_file_id"] == "file-1"
    assert event["partner"] == "MOMO"
    assert event["stage"] == "PERSISTING"
    assert event["error_code"] == "stage_summary_persist_failed"
    assert "traceback" not in event


@pytest.mark.asyncio
async def test_stage_summary_write_failure_does_not_change_ingestion_result() -> None:
    repository = MagicMock()
    repository.update_processing_stats = AsyncMock(return_value=True)
    repository.update_status = AsyncMock(return_value=True)
    repository.update_stage_summary = AsyncMock(side_effect=RuntimeError("db down"))
    logger = MagicMock()
    finalizer = IngestionRunFinalizer(logger)
    file_record = SimpleNamespace(id="file-1", partner="MOMO")
    state = IngestionRunState(
        run_id="runtime-1",
        partner="MOMO",
        current_stage="FINALIZING",
        total_rows=3,
        success_rows=2,
        rejected_rows=1,
    )

    await finalizer.complete(repository, file_record, state, 10.0)

    assert file_record.processing_status.value == "PARTIAL"
    assert file_record.total_rows == 3
    assert file_record.success_rows == 2
    assert file_record.failed_rows == 0
    logger.emit_ingestion_observability_write_failed.assert_called_once_with(
        run_id="runtime-1",
        source_file_id="file-1",
        partner="MOMO",
        stage="FINALIZING",
    )
