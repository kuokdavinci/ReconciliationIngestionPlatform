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
    
    def _create_mock_coll():
        coll = MagicMock()
        coll.count_documents = AsyncMock(return_value=0)
        coll.insert_one = AsyncMock()
        coll.insert_many = AsyncMock(return_value=[])
        coll.find_one = AsyncMock(return_value=None)
        coll.update_one = AsyncMock()
        coll.delete_many = AsyncMock()
        return coll

    mock_collection = _create_mock_coll()
    mock_collection.database = mock_db
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    app.state.db = mock_db
    app.state.mongo_client = MagicMock()
    return app, mock_collection


class _AsyncCursor:
    """Async iterator that yields documents, mimicking a MongoDB cursor."""

    def __init__(self, docs: list[dict]):
        self._docs = docs
        self._idx = 0
        self._limit = None
        self._skip = 0

    def sort(self, *args, **kwargs):
        return self

    def skip(self, value: int):
        self._skip = value
        return self

    def limit(self, value: int):
        self._limit = value
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        sliced_docs = self._docs[self._skip:]
        if self._limit is not None:
            sliced_docs = sliced_docs[:self._limit]

        if self._idx >= len(sliced_docs):
            raise StopAsyncIteration
        val = sliced_docs[self._idx]
        self._idx += 1
        return val


class _BackgroundTaskStub:
    def add_done_callback(self, callback):
        return None


def _discard_background_task(coro):
    coro.close()
    return _BackgroundTaskStub()


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
        assert data["limit"] == 25
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
        mock_collection.count_documents = AsyncMock(return_value=10)

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
        assert data["byStatus"]["MATCHED"] == 80
        assert data["byStatus"]["AMOUNT_MISMATCH"] == 20

    def test_missing_partner_returns_400(self):
        app, _ = _create_test_app()
        client = TestClient(app)
        response = client.get("/api/v1/reconciliation/stats", params={"date": "2024-07-07"})
        assert response.status_code == 400


class TestRunStatus:
    def test_prefers_active_waiting_review_run_over_later_unscoped_complete(self):
        app, mock_collection = _create_test_app()
        waiting_review_doc = {
            "_id": "run-waiting",
            "partner": "MOMO",
            "date": "2024-07-07",
            "triggerType": "SCHEDULER",
            "status": "WAITING_REVIEW",
            "message": "Waiting for review.",
            "sourceFileId": "file-001",
            "createdAt": "2024-07-07T09:00:00",
            "updatedAt": "2024-07-07T09:00:00",
        }
        mock_collection.find_one = AsyncMock(side_effect=[waiting_review_doc])

        client = TestClient(app)
        with patch("src.api.reconciliation._resolve_latest_run_context", new=AsyncMock(return_value={"source_file_id": "file-001"})):
            response = client.get(
                "/api/v1/reconciliation/run-status",
                params={"partner": "MOMO", "date": "2024-07-07"},
            )
        assert response.status_code == 200
        assert response.json()["run"]["status"] == "WAITING_REVIEW"


class TestRunReconciliation:
    @pytest.mark.asyncio
    async def test_run_reconciliation_returns_count(self):
        from src.api.reconciliation import run_reconciliation_now, RunReconciliationPayload
        app, mock_collection = _create_test_app()
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(db=mock_collection.database)),
            headers={"X-Actor": "admin"},
        )
        with (
            patch("src.api.reconciliation._resolve_latest_run_context", new=AsyncMock(return_value={"source_file_id": "file-001"})),
            patch("src.api.reconciliation._count_partner_rows_for_source_file", new=AsyncMock(return_value=20)),
            patch("src.api.reconciliation.ReconciliationEngine.reconcile", new=AsyncMock(return_value=[1, 2, 3])),
        ):
            response = await run_reconciliation_now(
                request,
                RunReconciliationPayload(partner="MOMO", date="2024-07-07"),
            )
        assert response["ok"] is True
        assert "run" in response
        assert response["run"]["partner"] == "MOMO"
        assert response["run"]["triggeredBy"] == "admin"

    @pytest.mark.asyncio
    async def test_run_reconciliation_requires_partner(self):
        from src.api.reconciliation import run_reconciliation_now, RunReconciliationPayload
        app, mock_collection = _create_test_app()
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(db=mock_collection.database)),
            headers={"X-Actor": "admin"},
        )
        with pytest.raises(HTTPException) as exc:
            await run_reconciliation_now(
                request,
                RunReconciliationPayload(partner="", date="2024-07-07"),
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_run_reconciliation_requires_actor(self):
        from src.api.reconciliation import run_reconciliation_now, RunReconciliationPayload
        app, mock_collection = _create_test_app()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=mock_collection.database)), headers={})
        with pytest.raises(HTTPException) as exc:
            await run_reconciliation_now(
                request,
                RunReconciliationPayload(partner="MOMO", date="2024-07-07"),
            )
        assert exc.value.status_code == 400
        assert "Actor is required" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_run_reconciliation_reuses_latest_source_file_context(self):
        from src.api.reconciliation import run_reconciliation_now, RunReconciliationPayload

        app, mock_collection = _create_test_app()
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(db=mock_collection.database)),
            headers={"X-Actor": "admin"},
        )
        queued_run = SimpleNamespace(
            id="run-queued",
            partner="MOMO",
            date="2024-07-07",
            trigger_type="MANUAL_RECONCILIATION",
            triggered_by="admin",
            status="QUEUED",
            message="Reconciliation is queued.",
            source_file_id="file-001",
            mapping_version="v2",
            validation_state="NOT_RUN",
            stats={},
            reconciliation_count=None,
            started_at=None,
            finished_at=None,
            created_at=None,
            updated_at=None,
            model_dump=lambda by_alias=True: {
                "_id": "run-queued",
                "partner": "MOMO",
                "date": "2024-07-07",
                "triggerType": "MANUAL_RECONCILIATION",
                "triggeredBy": "admin",
                "status": "QUEUED",
                "message": "Reconciliation is queued.",
                "sourceFileId": "file-001",
                "mappingVersion": "v2",
                "validationState": "NOT_RUN",
                "stats": {},
                "reconciliationCount": None,
                "createdAt": None,
                "updatedAt": None,
                "startedAt": None,
                "finishedAt": None,
            },
        )
        with (
            patch("src.api.reconciliation._resolve_latest_run_context", new=AsyncMock(return_value={"source_file_id": "file-001", "mapping_version": "v2"})),
            patch("src.api.reconciliation._count_partner_rows_for_source_file", new=AsyncMock(return_value=20)),
            patch("src.api.reconciliation.update_runtime_run", new=AsyncMock()) as mock_update_runtime_run,
            patch("src.api.reconciliation.PartnerRuntimeRunRepository.find_one", new=AsyncMock(return_value=queued_run)),
            patch("src.api.reconciliation.asyncio.create_task", side_effect=_discard_background_task),
        ):
            response = await run_reconciliation_now(
                request,
                RunReconciliationPayload(partner="MOMO", date="2024-07-07"),
            )

        assert response["ok"] is True
        assert response["run"]["sourceFileId"] == "file-001"
        assert response["run"]["mappingVersion"] == "v2"
        mock_update_runtime_run.assert_awaited()
