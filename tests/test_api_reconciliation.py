"""Tests for Reconciliation API endpoints."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException


def _create_test_app():
    from fastapi import FastAPI
    from src.api.reconciliation import router

    app = FastAPI()
    app.include_router(router)
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    app.state.db = mock_db
    app.state.mongo_client = MagicMock()
    return app, mock_collection


class _AsyncCursor:
    """Async iterator that yields documents, mimicking a MongoDB cursor."""

    def __init__(self, docs: list[dict]):
        self._docs = docs
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._docs):
            raise StopAsyncIteration
        val = self._docs[self._idx]
        self._idx += 1
        return val


class TestListResults:
    def test_missing_partner_returns_400(self):
        app, _ = _create_test_app()
        client = TestClient(app)
        response = client.get("/api/v1/reconciliation/results", params={"date": "2024-07-07"})
        assert response.status_code == 400
        assert "Partner identifier is required" in response.json()["detail"]

    def test_missing_date_returns_400(self):
        app, _ = _create_test_app()
        client = TestClient(app)
        response = client.get("/api/v1/reconciliation/results", params={"partner": "MOMO"})
        assert response.status_code == 400
        assert "Date parameter is required" in response.json()["detail"]

    def test_invalid_date_format_returns_400(self):
        app, _ = _create_test_app()
        client = TestClient(app)
        response = client.get(
            "/api/v1/reconciliation/results",
            params={"partner": "MOMO", "date": "invalid-date"},
        )
        assert response.status_code == 400
        assert "Invalid date format" in response.json()["detail"]

    def test_valid_request_returns_200_with_results(self):
        app, mock_collection = _create_test_app()
        mock_cursor = _AsyncCursor([])
        mock_collection.find = MagicMock(return_value=mock_cursor)

        client = TestClient(app)
        response = client.get(
            "/api/v1/reconciliation/results",
            params={"partner": "MOMO", "date": "2024-07-07"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "total" in data
        assert data["limit"] == 100
        assert data["offset"] == 0

    def test_limit_and_offset_work(self):
        app, mock_collection = _create_test_app()
        fake_docs = [
            {"_id": f"txn{i}", "partner": "MOMO", "date": "2024-07-07",
             "partnerTxnId": f"txn{i}", "reconciliationStatus": "MATCHED",
             "createdAt": "2024-07-07T00:00:00"}
            for i in range(10)
        ]

        mock_cursor = _AsyncCursor(fake_docs)
        mock_collection.find = MagicMock(return_value=mock_cursor)

        client = TestClient(app)
        response = client.get(
            "/api/v1/reconciliation/results",
            params={"partner": "MOMO", "date": "2024-07-07", "limit": 5, "offset": 5},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 5
        assert data["total"] == 10
        assert data["limit"] == 5
        assert data["offset"] == 5

    def test_returns_500_on_db_error(self):
        app, mock_collection = _create_test_app()
        mock_collection.find = MagicMock(side_effect=RuntimeError("DB connection lost"))

        client = TestClient(app)
        response = client.get(
            "/api/v1/reconciliation/results",
            params={"partner": "MOMO", "date": "2024-07-07"},
        )
        assert response.status_code == 500
        assert "Failed to list results" in response.json()["detail"]


class TestGetResult:
    def test_existing_id_returns_record(self):
        app, mock_collection = _create_test_app()
        mock_collection.find_one = AsyncMock(return_value={
            "_id": "txn123", "partner": "MOMO", "date": "2024-07-07",
            "partnerTxnId": "txn123", "reconciliationStatus": "MATCHED",
            "createdAt": "2024-07-07T00:00:00",
        })

        client = TestClient(app)
        response = client.get("/api/v1/reconciliation/results/txn123")
        assert response.status_code == 200
        assert response.json()["_id"] == "txn123"

    def test_non_existing_id_returns_404(self):
        app, mock_collection = _create_test_app()
        mock_collection.find_one = AsyncMock(return_value=None)

        client = TestClient(app)
        response = client.get("/api/v1/reconciliation/results/nonexistent")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


class TestStats:
    def test_valid_request_returns_stats(self):
        app, mock_collection = _create_test_app()

        mock_collection.aggregate = MagicMock(side_effect=[
            _AsyncCursor([
                {"_id": "MATCHED", "count": 80},
                {"_id": "AMOUNT_MISMATCH", "count": 20},
            ]),
            _AsyncCursor([
                {"_id": None, "total_partner_amount": 1000000, "total_internal_amount": 950000},
            ]),
        ])

        client = TestClient(app)
        response = client.get(
            "/api/v1/reconciliation/stats",
            params={"partner": "MOMO", "date": "2024-07-07"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["partner"] == "MOMO"
        assert data["total"] == 100
        assert data["by_status"]["MATCHED"] == 80
        assert data["by_status"]["AMOUNT_MISMATCH"] == 20

    def test_missing_partner_returns_400(self):
        app, _ = _create_test_app()
        client = TestClient(app)
        response = client.get("/api/v1/reconciliation/stats", params={"date": "2024-07-07"})
        assert response.status_code == 400


class TestRunReconciliation:
    @pytest.mark.asyncio
    async def test_run_reconciliation_returns_count(self):
        from src.api.reconciliation import run_reconciliation_now, RunReconciliationPayload
        app, mock_collection = _create_test_app()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=mock_collection.database)))
        with patch("src.api.reconciliation.ReconciliationEngine.reconcile", new=AsyncMock(return_value=[1, 2, 3])):
            response = await run_reconciliation_now(
                request,
                RunReconciliationPayload(partner="MOMO", date="2024-07-07"),
            )
        assert response["ok"] is True
        assert response["reconciliationCount"] == 3

    @pytest.mark.asyncio
    async def test_run_reconciliation_requires_partner(self):
        from src.api.reconciliation import run_reconciliation_now, RunReconciliationPayload
        app, mock_collection = _create_test_app()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=mock_collection.database)))
        with pytest.raises(HTTPException) as exc:
            await run_reconciliation_now(
                request,
                RunReconciliationPayload(partner="", date="2024-07-07"),
            )
        assert exc.value.status_code == 400
