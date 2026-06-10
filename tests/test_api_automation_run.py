"""Tests for automation run-now endpoint."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


def _create_test_app():
    from fastapi import FastAPI
    from src.api.automation import router

    app = FastAPI()
    app.include_router(router)
    mock_db = MagicMock()
    fetch_collection = MagicMock()
    mapping_collection = MagicMock()
    review_collection = MagicMock()

    def _get_collection(name):
        if name == "fetch_config":
            return fetch_collection
        if name == "reconciliation_mapping_config":
            return mapping_collection
        if name == "review_packet":
            return review_collection
        return MagicMock()

    mock_db.__getitem__ = MagicMock(side_effect=_get_collection)
    app.state.db = mock_db
    app.state.mongo_client = MagicMock()
    return app, fetch_collection


def test_run_automation_job_now():
    app, fetch_collection = _create_test_app()
    fetch_collection.find_one = AsyncMock(return_value={
        "_id": "ed7dcff9-f1e7-4b95-a459-6e1e0a210513",
        "partner": "ZALOPAY",
        "fetchMethod": "FILEDROP",
        "enabled": True,
        "schedule": "0 0 * * *",
        "localDownloadDir": "./downloads",
        "filedrop": {"directory": "sftp_data/zalopay_weird", "pattern": "*.csv"},
        "updatedAt": "2026-06-02T10:24:34.686000",
    })

    with patch("src.api.automation.run_fetch_config_once", new=AsyncMock(return_value={
        "success": True,
        "partner": "ZALOPAY",
        "filePath": "downloads/zalopay.csv",
        "fileSize": 512,
        "processingStatus": "COMPLETED",
    })):
        client = TestClient(app)
        response = client.post("/api/v1/automation/jobs/ZALOPAY/run", json={})
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["result"]["partner"] == "ZALOPAY"
