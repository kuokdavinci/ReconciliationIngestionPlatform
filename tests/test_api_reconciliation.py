"""Tests for Reconciliation API endpoints."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tests.asgi_test_client import TestClient
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
        self._limit: int | None = None
        self._skip: int = 0

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

    def test_date_bounds_follow_business_timezone(self):
        from src.api.reconciliation import _date_bounds

        start, end = _date_bounds("2026-08-10")

        assert start == datetime(2026, 8, 9, 17, tzinfo=timezone.utc)
        assert end == datetime(2026, 8, 10, 16, 59, 59, 999999, tzinfo=timezone.utc)

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

        with patch(
            "src.api.reconciliation.ReconciliationResultRepository.find_page_by_partner_and_date",
            AsyncMock(return_value=([], 0)),
        ):
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
        from src.models.reconciliation_result import ReconciliationResult
        from uuid import uuid4
        fake_results = [
            ReconciliationResult(
                id=str(uuid4()),
                partner="MOMO",
                partner_txn_id=f"txn{i}",
                reconciliation_status="MATCHED",
                date="2024-07-07",
                reconciliation_date=datetime(2024, 7, 7, tzinfo=timezone.utc),
            )
            for i in range(5)
        ]
        mock_find_page = AsyncMock(return_value=(fake_results, 10))

        with patch("src.api.reconciliation.ReconciliationResultRepository.find_page_by_partner_and_date", mock_find_page):
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
        mock_find_page = AsyncMock(side_effect=RuntimeError("DB connection lost"))

        with patch("src.api.reconciliation.ReconciliationResultRepository.find_page_by_partner_and_date", mock_find_page):
            client = TestClient(app)
            response = client.get(
                "/api/v1/reconciliation/results",
                params={"partner": "MOMO", "date": "2024-07-07"},
            )
            assert response.status_code == 500
            assert "Failed to list results" in response.json()["detail"]

    def test_results_include_all_partner_rows_for_business_date(self):
        app, _ = _create_test_app()
        from src.models.reconciliation_result import ReconciliationResult
        from uuid import uuid4

        legacy_result = ReconciliationResult(
            id=str(uuid4()),
            partner="MOMO",
            partner_txn_id="txn-legacy",
            reconciliation_status="MATCHED",
            date="2024-07-07",
            reconciliation_date=datetime(2024, 7, 7, tzinfo=timezone.utc),
        )
        mock_find_page = AsyncMock(return_value=([legacy_result], 1))

        with (
            patch(
                "src.api.reconciliation._resolve_latest_run_filters",
                new=AsyncMock(return_value={"source_file_id": "latest-file"}),
            ),
            patch(
                "src.api.reconciliation.ReconciliationResultRepository.find_page_by_partner_and_date",
                mock_find_page,
            ),
        ):
            response = TestClient(app).get(
                "/api/v1/reconciliation/results",
                params={"partner": "MOMO", "date": "2024-07-07"},
            )

        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert mock_find_page.await_count == 1
        assert "source_file_id" not in mock_find_page.await_args.kwargs
        assert "reconciliation_run_id" not in mock_find_page.await_args.kwargs


class TestGetResult:
    def test_existing_id_returns_record(self):
        app, mock_collection = _create_test_app()
        from src.models.reconciliation_result import ReconciliationResult
        res_obj = ReconciliationResult(
            id="txn123", partner="MOMO", date="2024-07-07",
            partner_txn_id="txn123", reconciliation_status="MATCHED",
            reconciliation_date=datetime(2024, 7, 7, tzinfo=timezone.utc),
        )
        mock_find_by_id = AsyncMock(return_value=res_obj)

        with patch("src.api.reconciliation.ReconciliationResultRepository.find_by_id", mock_find_by_id):
            client = TestClient(app)
            response = client.get("/api/v1/reconciliation/results/txn123")
            assert response.status_code == 200
            assert response.json()["_id"] == "txn123"

    def test_non_existing_id_returns_404(self):
        app, mock_collection = _create_test_app()
        mock_find_by_id = AsyncMock(return_value=None)

        with patch("src.api.reconciliation.ReconciliationResultRepository.find_by_id", mock_find_by_id):
            client = TestClient(app)
            response = client.get("/api/v1/reconciliation/results/nonexistent")
            assert response.status_code == 404
            assert "not found" in response.json()["detail"]


class TestStats:
    def test_valid_request_returns_stats(self):
        app, mock_collection = _create_test_app()
        mock_count = AsyncMock(return_value={"MATCHED": 80, "AMOUNT_MISMATCH": 20})
        mock_totals = AsyncMock(return_value={"total_partner_amount": 1000000, "total_internal_amount": 950000})

        with patch("src.api.reconciliation.ReconciliationResultRepository.count_by_status", mock_count), \
             patch("src.api.reconciliation.ReconciliationResultRepository.get_total_amounts", mock_totals):
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

    def test_stats_include_all_partner_rows_for_business_date(self):
        app, _ = _create_test_app()
        mock_count = AsyncMock(return_value={"MATCHED": 2})
        mock_totals = AsyncMock(
            return_value={"total_partner_amount": 200, "total_internal_amount": 200}
        )

        with (
            patch(
                "src.api.reconciliation._resolve_latest_run_filters",
                new=AsyncMock(return_value={"reconciliation_run_id": "run-current"}),
            ),
            patch(
                "src.api.reconciliation.ReconciliationResultRepository.count_by_status",
                mock_count,
            ),
            patch(
                "src.api.reconciliation.ReconciliationResultRepository.get_total_amounts",
                mock_totals,
            ),
        ):
            response = TestClient(app).get(
                "/api/v1/reconciliation/stats",
                params={"partner": "MOMO", "date": "2024-07-07"},
            )

        assert response.status_code == 200
        assert response.json()["total"] == 2
        assert mock_count.await_count == 1
        assert mock_totals.await_count == 1
        assert "source_file_id" not in mock_count.await_args.kwargs
        assert "reconciliation_run_id" not in mock_count.await_args.kwargs


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
    async def test_background_reconciliation_uses_api_engine_injection_seam(self):
        from src.api.reconciliation import _run_reconciliation_in_background

        db = MagicMock()
        db["partner_runtime_run"].find_one = AsyncMock(return_value={"_id": "run-1"})
        runner = MagicMock()
        runner.reconcile = AsyncMock(return_value=["result"])

        with (
            patch("src.api.reconciliation.ReconciliationEngine", return_value=runner) as engine_factory,
            patch("src.api.reconciliation.update_runtime_run", new=AsyncMock()),
            patch("src.api.reconciliation.record_audit_event", new=AsyncMock()),
        ):
            await _run_reconciliation_in_background(
                db,
                "run-1",
                "MOMO",
                "2024-07-07",
                source_file_id="file-1",
                mapping_version="v1",
            )

        engine_factory.assert_called_once()
        runner.reconcile.assert_awaited_once()

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
