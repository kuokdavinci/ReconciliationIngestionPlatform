"""Tests for automation run-now endpoint."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _create_test_app():
    from fastapi import FastAPI
    from src.api.automation import router

    app = FastAPI()
    app.include_router(router)
    mock_db = MagicMock()
    def _create_mock_coll():
        coll = MagicMock()
        coll.find_one = AsyncMock(return_value=None)
        coll.find = MagicMock(return_value=[])
        coll.count_documents = AsyncMock(return_value=0)
        coll.insert_one = AsyncMock()
        coll.insert_many = AsyncMock(return_value=[])
        coll.update_one = AsyncMock()
        coll.delete_many = AsyncMock()
        return coll

    fetch_collection = _create_mock_coll()
    mapping_collection = _create_mock_coll()
    review_collection = _create_mock_coll()

    def _get_collection(name):
        if name == "fetch_config":
            return fetch_collection
        if name == "reconciliation_mapping_config":
            return mapping_collection
        if name == "review_packet":
            return review_collection
        return _create_mock_coll()

    mock_db.__getitem__ = MagicMock(side_effect=_get_collection)
    app.state.db = mock_db
    app.state.mongo_client = MagicMock()
    return app, fetch_collection


@pytest.mark.asyncio
async def test_run_automation_job_now():
    from src.api.automation import run_automation_job_now

    app, fetch_collection = _create_test_app()
    fetch_collection.find_one = AsyncMock(return_value={
        "_id": "123e4567-e89b-12d3-a456-426614174000",
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
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(db=app.state.db)),
            headers={"X-Actor": "admin"},
        )
        payload = await run_automation_job_now(request, "ZALOPAY")
        assert payload["ok"] is True
        assert payload["actor"] == "admin"
        assert payload["partner"] == "ZALOPAY"
