"""Tests for automation visibility endpoints."""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient


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


def _create_test_app():
    from fastapi import FastAPI
    from src.api.automation import router

    app = FastAPI()
    app.include_router(router)
    mock_db = MagicMock()
    fetch_collection = MagicMock()
    packet_collection = MagicMock()

    def _get_collection(name):
        if name == "fetch_config":
            return fetch_collection
        if name == "review_packet":
            return packet_collection
        return MagicMock()

    mock_db.__getitem__ = MagicMock(side_effect=_get_collection)
    app.state.db = mock_db
    app.state.mongo_client = MagicMock()
    return app, fetch_collection, packet_collection


def test_list_automation_jobs_filters_to_scheduler_packets():
    app, fetch_collection, packet_collection = _create_test_app()
    fetch_collection.find = MagicMock(return_value=_AsyncCursor([
        {
            "_id": "job-001",
            "partner": "ZALOPAY",
            "fetchMethod": "FILEDROP",
            "schedule": "0 0 * * *",
            "enabled": True,
            "localDownloadDir": "./downloads",
            "methodConfig": {"directory": "sftp_data/zalopay_weird"},
            "updatedAt": "2026-06-02T10:24:34.686000",
        }
    ]))
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
