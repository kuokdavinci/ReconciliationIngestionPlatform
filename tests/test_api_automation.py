"""Tests for automation visibility endpoints."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tests.asgi_test_client import TestClient

from src.domain.ingestion.checkpoints import (
    CheckpointStatus,
    IngestionCheckpoint,
    IngestionMode,
    SourceUnitStatus,
    SourceUnitSummary,
)


class _AsyncCursor:
    def __init__(self, docs):
        self._docs = docs
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._docs):
            raise StopAsyncIteration
        item = self._docs[self._idx]
        self._idx += 1
        return item


def _checkpoint_raw(config_id: str, **overrides):
    values: dict[str, Any] = {
        "partner": "ZALOPAY",
        "fetchConfigId": config_id,
        "sourceType": "FILEDROP",
        "streamKey": "ZALOPAY:FILEDROP:filedrop://sftp_data/zalopay_weird/*.csv",
        "mode": IngestionMode.SCHEDULED,
    }
    values.update(overrides)
    return IngestionCheckpoint(**values).model_dump(by_alias=True)


def _create_test_app():
    from fastapi import FastAPI
    from src.api.automation import router

    app = FastAPI()
    app.include_router(router)
    mock_db = MagicMock()
    
    def _create_mock_coll():
        coll = MagicMock()
        coll.find_one = AsyncMock(return_value=None)
        coll.find = MagicMock(return_value=_AsyncCursor([]))
        coll.count_documents = AsyncMock(return_value=0)
        coll.insert_one = AsyncMock()
        coll.insert_many = AsyncMock(return_value=[])
        coll.update_one = AsyncMock()
        coll.delete_many = AsyncMock()
        return coll

    fetch_collection = _create_mock_coll()
    packet_collection = _create_mock_coll()
    runtime_run_collection = _create_mock_coll()
    recon_file_collection = _create_mock_coll()
    checkpoint_collection = _create_mock_coll()
    backfill_collection = _create_mock_coll()
    mapping_collection = _create_mock_coll()

    def _get_collection(name):
        if name == "fetch_config":
            return fetch_collection
        if name == "review_packet":
            return packet_collection
        if name == "partner_runtime_run":
            return runtime_run_collection
        if name == "reconciliation_file":
            return recon_file_collection
        if name == "ingestion_checkpoint":
            return checkpoint_collection
        if name == "backfill_run":
            return backfill_collection
        if name == "reconciliation_mapping_config":
            return mapping_collection
        return _create_mock_coll()

    mock_db.__getitem__ = MagicMock(side_effect=_get_collection)
    app.state.db = mock_db
    app.state.mongo_client = MagicMock()
    return (
        app,
        fetch_collection,
        packet_collection,
        runtime_run_collection,
        recon_file_collection,
        checkpoint_collection,
        backfill_collection,
        mapping_collection,
    )


def test_list_automation_jobs_filters_to_scheduler_packets():
    app, fetch_collection, packet_collection, _, _, _, backfill_collection, _ = _create_test_app()
    fetch_collection.find = MagicMock(return_value=_AsyncCursor([
        {
            "_id": "123e4567-e89b-12d3-a456-426614174000",
            "partner": "ZALOPAY",
            "fetchMethod": "FILEDROP",
            "schedule": "0 0 * * *",
            "enabled": True,
            "localDownloadDir": "./downloads",
            "methodConfig": {"directory": "sftp_data/zalopay_weird"},
            "updatedAt": "2026-06-02T10:24:34.686000",
        }
    ]))
    backfill_collection.find_one = AsyncMock(return_value={
        "_id": "backfill-vnpay-1",
        "partner": "ZALOPAY",
        "fetchConfigId": "123e4567-e89b-12d3-a456-426614174000",
        "mode": "BACKFILL",
        "status": "WAITING_CONFIG",
        "fromDate": "2026-08-07",
        "toDate": "2026-08-11",
        "currentDate": "2026-08-10",
        "completedDays": 1,
        "totalDays": 3,
        "approvalRequired": True,
        "days": [],
    })
    packet_collection.find = MagicMock(return_value=_AsyncCursor([
        {
            "_id": "pkt-scheduler-1",
            "sourceType": "SCHEDULER_JOB",
            "partner": "ZALOPAY",
            "fileName": "scheduled.csv",
            "fileTypeDetected": "SETTLEMENT",
            "recommendedAction": {"reason": "Structure drift detected."},
            "parseStrategy": {"strategy": "AI inferred parser from scheduled partner fetch sample"},
            "validationGates": [],
            "samplePreview": [],
            "riskSummary": {"severity": "high"},
            "status": "PENDING",
            "createdAt": "2026-06-04T03:00:00",
        },
        {
            "_id": "pkt-scheduler-duplicate",
            "sourceType": "SCHEDULER_JOB",
            "partner": "ZALOPAY",
            "fileName": "scheduled-page-1.csv",
            "fileTypeDetected": "SETTLEMENT",
            "recommendedAction": {"reason": "Duplicate retry packet."},
            "parseStrategy": {"strategy": "AI inferred parser from scheduled partner fetch sample"},
            "validationGates": [],
            "samplePreview": [],
            "riskSummary": {"severity": "high"},
            "status": "PENDING",
            "createdAt": "2026-06-04T02:59:00",
        },
        {
            "_id": "pkt-upload-1",
            "sourceType": "UPLOAD",
            "partner": "ZALOPAY",
            "fileName": "manual.csv",
            "fileTypeDetected": "SETTLEMENT",
            "recommendedAction": {"reason": "Manual upload review."},
            "parseStrategy": {"strategy": "Manual upload parser"},
            "validationGates": [],
            "samplePreview": [],
            "riskSummary": {"severity": "medium"},
            "status": "PENDING",
            "createdAt": "2026-06-04T04:00:00",
        },
        {
            "_id": "pkt-scheduler-2",
            "sourceType": "SCHEDULER_JOB",
            "partner": "ZALOPAY",
            "fileName": "scheduled-reviewed.csv",
            "fileTypeDetected": "SETTLEMENT",
            "recommendedAction": {"reason": "Reviewed scheduler packet."},
            "parseStrategy": {"strategy": "AI inferred parser from scheduled partner fetch sample"},
            "validationGates": [],
            "samplePreview": [],
            "riskSummary": {"severity": "medium"},
            "status": "APPROVED",
            "decisionMode": "APPROVE_KEEP_CURRENT_FOR_FILE",
            "createdAt": "2026-06-04T02:00:00",
            "reviewedAt": "2026-06-04T02:15:00",
        },
    ]))

    client = TestClient(app)
    response = client.get("/api/v1/automation/jobs")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["jobs"]) == 1

    job = payload["jobs"][0]
    assert job["partner"] == "ZALOPAY"
    assert job["pendingReviewPackets"] == 1
    assert len(job["recentPackets"]) == 2
    assert all(packet["sourceType"] == "SCHEDULER_JOB" for packet in job["recentPackets"])
    assert job["recentPackets"][1]["decisionMode"] == "APPROVE_KEEP_CURRENT_FOR_FILE"
    assert job["activeBackfill"]["currentDate"] == "2026-08-10"


def test_list_automation_jobs_hides_equivalent_pending_backfill_packet():
    app, fetch_collection, packet_collection, _, _, _, backfill_collection, _ = _create_test_app()
    fetch_collection.find = MagicMock(return_value=_AsyncCursor([
        {
            "_id": "123e4567-e89b-12d3-a456-426614174000",
            "partner": "VNPAY",
            "fetchMethod": "FILEDROP",
            "schedule": "none",
            "enabled": True,
            "localDownloadDir": "./downloads",
            "methodConfig": {"directory": "mock_data"},
            "updatedAt": "2026-08-13T09:30:59.048000",
        }
    ]))
    packet_collection.find = MagicMock(return_value=_AsyncCursor([
        {
            "_id": "pkt-vnpay-duplicate",
            "sourceType": "SCHEDULER_JOB",
            "partner": "VNPAY",
            "fileName": "settlement_VNPAY_20260813.xlsx",
            "fileTypeDetected": "SETTLEMENT",
            "structureSignature": {
                "headers": ["id", "trace", "amount"],
                "columnCount": 3,
                "hash": "same-structure",
            },
            "recommendedAction": {},
            "parseStrategy": {},
            "validationGates": [],
            "samplePreview": [],
            "riskSummary": {},
            "status": "PENDING",
            "createdAt": "2026-08-13T09:32:27.556000",
        },
        {
            "_id": "pkt-vnpay-start-date",
            "sourceType": "SCHEDULER_JOB",
            "partner": "VNPAY",
            "fileName": "settlement_VNPAY_20260810.xlsx",
            "fileTypeDetected": "SETTLEMENT",
            "structureSignature": {
                "headers": ["id", "trace", "amount"],
                "columnCount": 3,
            },
            "recommendedAction": {},
            "parseStrategy": {},
            "validationGates": [],
            "samplePreview": [],
            "riskSummary": {},
            "status": "APPROVED",
            "createdAt": "2026-08-10T00:00:00",
        },
    ]))
    backfill_collection.find_one = AsyncMock(return_value=None)

    client = TestClient(app)
    response = client.get("/api/v1/automation/jobs")

    assert response.status_code == 200
    job = response.json()["jobs"][0]
    assert job["pendingReviewPackets"] == 0
    assert [packet["_id"] for packet in job["recentPackets"]] == ["pkt-vnpay-start-date"]


def test_list_automation_jobs_shows_pending_packet_for_new_source_file():
    app, fetch_collection, packet_collection, _, _, _, backfill_collection, _ = _create_test_app()
    fetch_collection.find = MagicMock(return_value=_AsyncCursor([
        {
            "_id": "123e4567-e89b-12d3-a456-426614174000",
            "partner": "MOMO",
            "fetchMethod": "FILEDROP",
            "schedule": "none",
            "enabled": True,
            "localDownloadDir": "./downloads",
            "methodConfig": {"directory": "mock_data"},
            "updatedAt": "2026-08-17T09:30:59.048000",
        }
    ]))
    same_structure = {
        "headers": ["id", "trace", "amount"],
        "columnCount": 3,
        "hash": "same-structure",
    }
    packet_collection.find = MagicMock(return_value=_AsyncCursor([
        {
            "_id": "pkt-momo-phase2",
            "sourceType": "SCHEDULER_JOB",
            "partner": "MOMO",
            "fileName": "settlement_MOMO_20260817_phase2.xlsx",
            "sourceFileId": "file-phase2",
            "sourceFilePath": "/mock_data/settlement_MOMO_20260817_phase2.xlsx",
            "fileTypeDetected": "SETTLEMENT",
            "structureSignature": same_structure,
            "recommendedAction": {},
            "parseStrategy": {},
            "validationGates": [],
            "samplePreview": [],
            "riskSummary": {},
            "status": "PENDING",
            "createdAt": "2026-08-17T03:00:00+00:00",
        },
        {
            "_id": "pkt-momo-phase1",
            "sourceType": "SCHEDULER_JOB",
            "partner": "MOMO",
            "fileName": "settlement_MOMO_20260817.xlsx",
            "sourceFileId": "file-phase1",
            "sourceFilePath": "/mock_data/settlement_MOMO_20260817.xlsx",
            "fileTypeDetected": "SETTLEMENT",
            "structureSignature": same_structure,
            "recommendedAction": {},
            "parseStrategy": {},
            "validationGates": [],
            "samplePreview": [],
            "riskSummary": {},
            "status": "APPROVED",
            "createdAt": "2026-08-17T02:00:00+00:00",
        },
    ]))
    backfill_collection.find_one = AsyncMock(return_value=None)

    response = TestClient(app).get("/api/v1/automation/jobs")

    assert response.status_code == 200
    job = response.json()["jobs"][0]
    assert job["pendingReviewPackets"] == 1
    assert job["recentPackets"][0]["_id"] == "pkt-momo-phase2"


@pytest.mark.asyncio
async def test_backfill_review_packet_attachment_is_scoped_to_current_business_date():
    from src.api.automation import _attach_pending_backfill_review_packet

    packet_collection = MagicMock()
    packet_collection.find_one = AsyncMock(return_value={"_id": "packet-2026-08-10"})
    packet_collection.update_one = AsyncMock()
    backfill_collection = MagicMock()
    backfill_collection.find_one = AsyncMock(return_value={"currentDate": "2026-08-10"})
    db = MagicMock()
    db.__getitem__ = MagicMock(
        side_effect=lambda name: {
            "review_packet": packet_collection,
            "backfill_run": backfill_collection,
        }[name]
    )

    packet_id = await _attach_pending_backfill_review_packet(db, "VNPAY", "backfill-1")

    assert packet_id == "packet-2026-08-10"
    packet_query = packet_collection.find_one.await_args.args[0]
    assert packet_query["reconciliationDate"]["$gte"].date().isoformat() == "2026-08-10"
    assert packet_query["reconciliationDate"]["$lte"].date().isoformat() == "2026-08-10"


@pytest.mark.asyncio
async def test_backfill_review_packet_is_not_reassigned_to_a_duplicate_parent():
    from src.api.automation import _attach_pending_backfill_review_packet

    packet_collection = MagicMock()
    packet_collection.find_one = AsyncMock(return_value={
        "_id": "packet-2026-08-10",
        "backfillRunId": "existing-backfill",
    })
    packet_collection.update_one = AsyncMock()
    backfill_collection = MagicMock()
    backfill_collection.find_one = AsyncMock(return_value={"currentDate": "2026-08-10"})
    db = MagicMock()
    db.__getitem__ = MagicMock(
        side_effect=lambda name: {
            "review_packet": packet_collection,
            "backfill_run": backfill_collection,
        }[name]
    )

    packet_id = await _attach_pending_backfill_review_packet(db, "VNPAY", "duplicate-backfill")

    assert packet_id is None
    packet_collection.update_one.assert_not_awaited()


def test_duplicate_run_takes_precedence_over_pending_file_status():
    app, fetch_collection, _, runtime_run_collection, recon_file_collection, _, _, _ = _create_test_app()
    fetch_collection.find = MagicMock(return_value=_AsyncCursor([
        {
            "_id": "123e4567-e89b-12d3-a456-426614174000",
            "partner": "MOMO",
            "fetchMethod": "FILEDROP",
            "schedule": "0 0 * * *",
            "enabled": True,
            "localDownloadDir": "./mock_data",
            "filedrop": {"directory": "./mock_data", "pattern": "settlement_MOMO_*.xlsx"},
            "updatedAt": "2026-08-06T04:00:00",
        }
    ]))
    runtime_run_collection.find_one = AsyncMock(return_value={
        "_id": "run-duplicate",
        "partner": "MOMO",
        "date": "2026-08-06",
        "triggerType": "SCHEDULER",
        "status": "COMPLETED",
        "message": "Sequential source-unit ingestion completed successfully.",
        "stats": {
            "outcome": "FILE_DUPLICATE",
            "reconciliationSkipped": True,
        },
        "createdAt": "2026-08-06T04:17:00",
        "updatedAt": "2026-08-06T04:17:00",
    })
    recon_file_collection.find_one = AsyncMock(return_value={
        "_id": "file-existing",
        "partner": "MOMO",
        "fileName": "settlement_MOMO_20260806_phase2.xlsx",
        "processingStatus": "COMPLETED",
        "reconciliationDate": "2026-08-06T00:00:00",
        "createdAt": "2026-08-06T04:16:00",
    })

    client = TestClient(app)
    response = client.get("/api/v1/automation/jobs")

    assert response.status_code == 200
    job = response.json()["jobs"][0]
    assert job["duplicateOutcome"] == "FILE_DUPLICATE"
    assert job["safeDuplicate"] is True
    assert job["status"] == "SAFE_DUPLICATE"
    assert job["hasPendingFile"] is False
    assert job["statusMessage"] == (
        "File already processed. Ingestion and reconciliation were skipped safely."
    )


def test_list_automation_jobs_exposes_safe_recovery_read_model():
    app, fetch_collection, packet_collection, runtime_run_collection, recon_file_collection, checkpoint_collection, _, _ = _create_test_app()
    config_id = "123e4567-e89b-12d3-a456-426614174000"
    fetch_collection.find = MagicMock(return_value=_AsyncCursor([
        {
            "_id": config_id,
            "partner": "VIETTELPAY",
            "fetchMethod": "API",
            "schedule": "0 0 * * *",
            "enabled": True,
            "api": {
                "baseUrl": "https://private.example/api",
                "pagination": {"pageParam": "page", "maxPages": 3},
            },
            "updatedAt": "2026-08-06T04:00:00",
        }
    ]))
    packet_collection.find = MagicMock(return_value=_AsyncCursor([]))
    runtime_run_collection.find_one = AsyncMock(return_value={
        "_id": "run-failed",
        "partner": "VIETTELPAY",
        "date": "2026-08-06",
        "triggerType": "SCHEDULER",
        "status": "FAILED",
        "message": "Gateway timeout while fetching page 2",
        "stats": {},
        "createdAt": "2026-08-06T04:17:00",
        "updatedAt": "2026-08-06T04:17:00",
    })
    recon_file_collection.find_one = AsyncMock(return_value=None)
    checkpoint = IngestionCheckpoint(
        partner="VIETTELPAY",
        fetchConfigId=config_id,
        sourceType="API",
        streamKey="VIETTELPAY:API:https://private.example/api",
        mode=IngestionMode.SCHEDULED,
        status=CheckpointStatus.FAILED,
        currentUnitKey="page:2",
        lastCompletedUnitKey="page:1",
        cursorBefore="cursor-1",
        attemptCount=2,
        errorCode="fetch_timeout",
        lastError="Gateway timeout while fetching page 2",
        retryable=True,
        unitTimeline=[
            SourceUnitSummary(
                unitKey="page:1",
                page=1,
                status=SourceUnitStatus.COMPLETED,
            ),
            SourceUnitSummary(
                unitKey="page:2",
                page=2,
                status=SourceUnitStatus.FAILED,
                errorCode="fetch_timeout",
                lastError="Gateway timeout while fetching page 2",
                attemptCount=2,
            ),
        ],
    )
    checkpoint_collection.find = MagicMock(return_value=_AsyncCursor([
        checkpoint.model_dump(by_alias=True)
    ]))

    response = TestClient(app).get("/api/v1/automation/jobs")

    assert response.status_code == 200
    recovery = response.json()["jobs"][0]["recovery"]
    assert recovery["status"] == "FAILED"
    assert recovery["streamKey"] == "VIETTELPAY:API:scheduled"
    assert recovery["lastCompletedUnitKey"] == "page:1"
    assert recovery["currentUnitKey"] == "page:2"
    assert recovery["currentPage"] == 2
    assert recovery["attemptCount"] == 2
    assert recovery["maxAttempts"] == 3
    assert recovery["duplicateCount"] == 0
    assert recovery["units"][1]["status"] == "FAILED"
    assert "private.example" not in str(recovery)


@pytest.mark.asyncio
async def test_retry_automation_job_resumes_failed_checkpoint_with_actor():
    from src.api.automation import retry_automation_job
    from src.api.automation import settings
    from src.domain.runtime.models import (
        PartnerRuntimeRun,
        PartnerRuntimeRunStatus,
        PartnerRuntimeTriggerType,
    )

    app, fetch_collection, _, _, _, checkpoint_collection, _, _ = _create_test_app()
    config_id = "123e4567-e89b-12d3-a456-426614174000"
    fetch_collection.find_one = AsyncMock(return_value={
        "_id": config_id,
        "partner": "ZALOPAY",
        "fetchMethod": "FILEDROP",
        "enabled": True,
        "filedrop": {"directory": "sftp_data/zalopay_weird", "pattern": "*.csv"},
        "updatedAt": "2026-08-06T04:00:00",
    })
    checkpoint = IngestionCheckpoint(
        partner="ZALOPAY",
        fetchConfigId=config_id,
        sourceType="FILEDROP",
        streamKey="ZALOPAY:FILEDROP:filedrop://sftp_data/zalopay_weird/*.csv",
        mode=IngestionMode.SCHEDULED,
        status=CheckpointStatus.FAILED,
        currentUnitKey="file:20260806.csv",
        retryable=True,
        nextRetryAt=datetime.now(UTC) + timedelta(minutes=1),
    )
    checkpoint_collection.find_one = AsyncMock(
        return_value=checkpoint.model_dump(by_alias=True)
    )
    checkpoint_collection.update_one.return_value = MagicMock(modified_count=1)
    queued_run = PartnerRuntimeRun(
        partner="ZALOPAY",
        date="2026-08-06",
        triggerType=PartnerRuntimeTriggerType.SCHEDULER,
        triggeredBy="ops-user",
        status=PartnerRuntimeRunStatus.QUEUED,
        message="Recovery retry queued from checkpoint.",
    )

    def _discard_background_task(coro):
        coro.close()
        task = MagicMock()
        task.add_done_callback = MagicMock()
        return task

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db=app.state.db)),
        headers={"X-Actor": "ops-user"},
    )
    with (
            patch(
                "src.api.automation.PartnerRuntimeRunRepository.create",
                new=AsyncMock(return_value=queued_run),
            ),
        patch("src.api.automation.asyncio.create_task", side_effect=_discard_background_task),
        patch.object(settings, "automation_orchestrator", "local"),
    ):
        payload = await retry_automation_job(request, "ZALOPAY")

    assert payload["ok"] is True
    assert payload["actor"] == "ops-user"
    assert payload["resumedFromUnitKey"] == "file:20260806.csv"
    assert payload["runtimeRunId"] == str(queued_run.id)
    update = checkpoint_collection.update_one.await_args.args[1]
    assert update["$set"]["resolutionMetadata"]["operatorId"] == "ops-user"


@pytest.mark.asyncio
async def test_retry_automation_job_rejects_blocked_checkpoint():
    from fastapi import HTTPException

    from src.api.automation import retry_automation_job

    app, fetch_collection, _, _, _, checkpoint_collection, _, _ = _create_test_app()
    config_id = "123e4567-e89b-12d3-a456-426614174000"
    fetch_collection.find_one = AsyncMock(return_value={
        "_id": config_id,
        "partner": "ZALOPAY",
        "fetchMethod": "FILEDROP",
        "enabled": True,
        "filedrop": {"directory": "sftp_data/zalopay_weird", "pattern": "*.csv"},
        "updatedAt": "2026-08-06T04:00:00",
    })
    checkpoint_collection.find_one = AsyncMock(return_value=_checkpoint_raw(
        config_id,
        status=CheckpointStatus.BLOCKED,
        retryable=False,
        currentUnitKey="file:20260806.csv",
    ))
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db=app.state.db)),
        headers={"X-Actor": "ops-user"},
    )

    with pytest.raises(HTTPException) as error:
        await retry_automation_job(request, "ZALOPAY")

    assert error.value.status_code == 409
    assert "BLOCKED" in str(error.value.detail)


@pytest.mark.asyncio
async def test_retry_automation_job_rejects_live_processing_claim():
    from fastapi import HTTPException

    from src.api.automation import retry_automation_job

    app, fetch_collection, _, _, _, checkpoint_collection, _, _ = _create_test_app()
    config_id = "123e4567-e89b-12d3-a456-426614174000"
    fetch_collection.find_one = AsyncMock(return_value={
        "_id": config_id,
        "partner": "ZALOPAY",
        "fetchMethod": "FILEDROP",
        "enabled": True,
        "filedrop": {"directory": "sftp_data/zalopay_weird", "pattern": "*.csv"},
        "updatedAt": "2026-08-06T04:00:00",
    })
    checkpoint_collection.find_one = AsyncMock(return_value=_checkpoint_raw(
        config_id,
        status=CheckpointStatus.PROCESSING,
        currentUnitKey="file:20260806.csv",
        startedAt=datetime.now(UTC),
    ))
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db=app.state.db)),
        headers={"X-Actor": "ops-user"},
    )

    with pytest.raises(HTTPException) as error:
        await retry_automation_job(request, "ZALOPAY")

    assert error.value.status_code == 409
    assert "live source-unit claim" in str(error.value.detail)


@pytest.mark.asyncio
async def test_run_automation_job_rejects_live_processing_claim():
    from fastapi import HTTPException

    from src.api.automation import run_automation_job_now

    app, fetch_collection, _, _, _, checkpoint_collection, _, _ = _create_test_app()
    config_id = "123e4567-e89b-12d3-a456-426614174000"
    fetch_collection.find_one = AsyncMock(return_value={
        "_id": config_id,
        "partner": "ZALOPAY",
        "fetchMethod": "FILEDROP",
        "enabled": True,
        "filedrop": {"directory": "sftp_data/zalopay_weird", "pattern": "*.csv"},
        "updatedAt": "2026-08-06T04:00:00",
    })
    checkpoint_collection.find_one = AsyncMock(return_value=_checkpoint_raw(
        config_id,
        status=CheckpointStatus.PROCESSING,
        currentUnitKey="file:20260806.csv",
        startedAt=datetime.now(UTC),
    ))
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db=app.state.db)),
        headers={"X-Actor": "ops-user"},
    )

    with pytest.raises(HTTPException) as error:
        await run_automation_job_now(request, "ZALOPAY")

    assert error.value.status_code == 409
    assert "live source-unit claim" in str(error.value.detail)


@pytest.mark.asyncio
async def test_run_automation_job_rejects_active_backfill():
    from fastapi import HTTPException

    from src.api.automation import run_automation_job_now
    from src.domain.backfill.models import BackfillDayRecord, BackfillRun, BackfillRunStatus

    app, fetch_collection, _, _, _, _, _, _ = _create_test_app()
    config_id = "123e4567-e89b-12d3-a456-426614174000"
    fetch_collection.find_one = AsyncMock(return_value={
        "_id": config_id,
        "partner": "VNPAY",
        "fetchMethod": "FILEDROP",
        "enabled": True,
        "filedrop": {"directory": "mock_data", "pattern": "*.xlsx"},
        "updatedAt": "2026-08-06T04:00:00",
    })
    active_backfill = BackfillRun(
        _id="backfill-vnpay-1",
        partner="VNPAY",
        fetchConfigId=config_id,
        status=BackfillRunStatus.WAITING_CONFIG,
        fromDate=datetime(2026, 8, 10, tzinfo=UTC).date(),
        toDate=datetime(2026, 8, 13, tzinfo=UTC).date(),
        currentDate=datetime(2026, 8, 10, tzinfo=UTC).date(),
        totalDays=4,
        approvalRequired=True,
        days=[BackfillDayRecord(businessDate=datetime(2026, 8, 10, tzinfo=UTC).date())],
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db=app.state.db)),
        headers={"X-Actor": "ops-user"},
    )

    with patch(
        "src.api.automation.BackfillRunRepository.find_latest_active_by_partner",
        new=AsyncMock(return_value=active_backfill),
    ), pytest.raises(HTTPException) as error:
        await run_automation_job_now(request, "VNPAY")

    assert error.value.status_code == 409
    assert "Backfill is WAITING_CONFIG at 2026-08-10" in str(error.value.detail)
    assert "instead of Run now" in str(error.value.detail)


@pytest.mark.asyncio
async def test_resolve_automation_recovery_requires_reason_and_records_audit_event():
    from src.api.automation import resolve_automation_recovery

    app, fetch_collection, _, _, _, checkpoint_collection, _, _ = _create_test_app()
    config_id = "123e4567-e89b-12d3-a456-426614174000"
    fetch_collection.find_one = AsyncMock(return_value={
        "_id": config_id,
        "partner": "ZALOPAY",
        "fetchMethod": "FILEDROP",
        "enabled": True,
        "filedrop": {"directory": "sftp_data/zalopay_weird", "pattern": "*.csv"},
        "updatedAt": "2026-08-06T04:00:00",
    })
    checkpoint_collection.find_one = AsyncMock(return_value=_checkpoint_raw(
        config_id,
        status=CheckpointStatus.BLOCKED,
        retryable=False,
        currentUnitKey="file:20260806.csv",
    ))
    checkpoint_collection.update_one.return_value = MagicMock(modified_count=1)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db=app.state.db)),
        headers={"X-Actor": "ops-user"},
        json=AsyncMock(return_value={"action": "SKIP", "reason": "Validated duplicate source file"}),
    )

    with patch("src.api.automation.record_audit_event", new=AsyncMock()) as record_audit:
        payload = await resolve_automation_recovery(request, "ZALOPAY")

    assert payload["ok"] is True
    assert payload["action"] == "SKIP"
    assert payload["unitKey"] == "file:20260806.csv"
    record_audit.assert_awaited_once()
    audit_kwargs = record_audit.await_args.kwargs
    assert audit_kwargs["entity_id"] == "ZALOPAY:FILEDROP:scheduled"
    assert audit_kwargs["metadata"]["reason"] == "Validated duplicate source file"


def test_list_jobs_marks_airflow_up_for_retry_as_active_runtime():
    from src.config.settings import settings
    from src.domain.runtime.models import (
        PartnerRuntimeRun,
        PartnerRuntimeRunStatus,
        PartnerRuntimeTriggerType,
        RuntimeOrchestrationContext,
    )

    app, fetch_collection, _, _, _, _, _, _ = _create_test_app()
    fetch_collection.find = MagicMock(return_value=_AsyncCursor([{
        "_id": "123e4567-e89b-12d3-a456-426614174000",
        "partner": "VIETTELPAY",
        "fetchMethod": "API",
        "schedule": "0 0 * * *",
        "enabled": True,
        "api": {"baseUrl": "http://viettelpay-mock:8001/settlement"},
        "updatedAt": "2026-08-09T01:02:03+00:00",
    }]))
    latest_run = PartnerRuntimeRun(
        partner="VIETTELPAY",
        date="2026-08-09",
        triggerType=PartnerRuntimeTriggerType.SCHEDULER,
        status=PartnerRuntimeRunStatus.FAILED,
        orchestration=RuntimeOrchestrationContext(
            dagId="reconciliation_ingestion",
            dagRunId="manual__runtime-1",
            taskId="run_stream",
            mapIndex=0,
        ),
    )
    with (
        patch.object(settings, "automation_orchestrator", "airflow"),
        patch(
            "src.api.automation.PartnerRuntimeRunRepository.find_latest_by_partner",
            new=AsyncMock(return_value=latest_run),
        ),
        patch(
            "src.api.automation.PartnerRuntimeRunRepository.find_recent_by_partner",
            new=AsyncMock(return_value=[]),
        ),
        patch("src.api.automation._airflow_task_state", new=AsyncMock(return_value="up_for_retry")),
    ):
        response = TestClient(app).get("/api/v1/automation/jobs")

    assert response.status_code == 200
    job = response.json()["jobs"][0]
    assert job["status"] == "RETRYING"
    assert job["activeRuntimeRun"]["orchestration"]["taskState"] == "up_for_retry"


def test_start_backfill_route_rejects_missing_or_disabled_configs():
    app, fetch_collection, _, _, _, _, _, _ = _create_test_app()
    fetch_collection.find_one = AsyncMock(return_value=None)

    client = TestClient(app)
    response = client.post(
        "/api/v1/automation/jobs/VNPAY/backfill",
        headers={"X-Actor": "ops-user"},
        json={"fromDate": "2026-08-07", "toDate": "2026-08-11"},
    )
    assert response.status_code == 404

    fetch_collection.find_one = AsyncMock(return_value={
        "_id": "123e4567-e89b-12d3-a456-426614174001",
        "partner": "VNPAY",
        "fetchMethod": "FILEDROP",
        "enabled": False,
        "filedrop": {"directory": "./mock_data/vnpay", "pattern": "*.xlsx"},
        "updatedAt": "2026-08-12T01:02:03+00:00",
    })
    response = client.post(
        "/api/v1/automation/jobs/VNPAY/backfill",
        headers={"X-Actor": "ops-user"},
        json={"fromDate": "2026-08-07", "toDate": "2026-08-11"},
    )
    assert response.status_code == 400
    assert "disabled" in response.json()["detail"].lower()


def test_start_backfill_route_validates_date_range():
    app, fetch_collection, _, _, _, _, _, _ = _create_test_app()
    fetch_collection.find_one = AsyncMock(return_value={
        "_id": "123e4567-e89b-12d3-a456-426614174001",
        "partner": "VNPAY",
        "fetchMethod": "FILEDROP",
        "enabled": True,
        "filedrop": {"directory": "./mock_data/vnpay", "pattern": "*.xlsx"},
        "updatedAt": "2026-08-12T01:02:03+00:00",
    })

    response = TestClient(app).post(
        "/api/v1/automation/jobs/VNPAY/backfill",
        headers={"X-Actor": "ops-user"},
        json={"fromDate": "2026-08-12", "toDate": "2026-08-11"},
    )

    assert response.status_code == 400
    assert "fromDate" in response.json()["detail"]


def test_get_backfill_run_status_returns_serialized_parent():
    from src.domain.backfill.models import BackfillDayRecord, BackfillRun, BackfillRunStatus

    app, _, _, _, _, _, backfill_collection, _ = _create_test_app()
    run = BackfillRun(
        _id="backfill-1",
        partner="VNPAY",
        fetchConfigId="cfg-1",
        mode=IngestionMode.BACKFILL,
        status=BackfillRunStatus.WAITING_CONFIG,
        fromDate=datetime(2026, 8, 7, tzinfo=UTC).date(),
        toDate=datetime(2026, 8, 11, tzinfo=UTC).date(),
        currentDate=datetime(2026, 8, 7, tzinfo=UTC).date(),
        completedDays=0,
        totalDays=3,
        approvalRequired=True,
        days=[BackfillDayRecord(businessDate=datetime(2026, 8, 7, tzinfo=UTC).date())],
    )
    backfill_collection.find_one = AsyncMock(return_value=run.model_dump(by_alias=True, mode="json"))

    response = TestClient(app).get("/api/v1/automation/backfill-runs/backfill-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["_id"] == "backfill-1"
    assert payload["status"] == "WAITING_CONFIG"
    assert payload["days"][0]["businessDate"] == "2026-08-07"
