"""Tests for Data Explorer API endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

from tests.asgi_test_client import TestClient


def _create_test_app():
    from fastapi import FastAPI
    from src.api.data_explorer import router

    app = FastAPI()
    app.include_router(router)
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    app.state.db = mock_db
    app.state.mongo_client = MagicMock()
    return app, mock_db, mock_collection


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


class TestListTransactions:
    def test_missing_partner_and_date_returns_200(self):
        app, _, _ = _create_test_app()
        mock_find_many = AsyncMock(return_value=[])

        with patch(
            "src.api.data_explorer.DataContainerRepository.find_many",
            mock_find_many,
        ):
            client = TestClient(app)
            response = client.get("/api/v1/data/transactions")

        assert response.status_code == 200
        data = response.json()
        assert "transactions" in data
        assert data["total"] == 0
        mock_find_many.assert_awaited_once_with({})

    def test_with_partner_filter(self):
        app, mock_db, _ = _create_test_app()
        _id = "550e8400-e29b-41d4-a716-446655440000"
        req_id = "550e8400-e29b-41d4-a716-446655440001"
        src_id = "550e8400-e29b-41d4-a716-446655440002"
        fake_docs = [
            {"_id": _id, "identify": "MOMO", "workflowType": "RECON",
             "reconciliationDate": "2024-07-07T00:00:00Z", "operationStatus": "DONE",
             "reconciliationStatus": "", "connectorData": "", "extraData": "",
             "sourceFileId": src_id,
             "partnerData": {"_id": "pd-1", "status": "SUCCESS", "amount": 100000, "currency": "VND"},
             "createdBy": "system", "createdDate": "2024-07-07T00:00:00Z",
             "lastModifiedBy": "system", "lastModifiedDate": "2024-07-07T00:00:00Z",
             "requestId": req_id},
        ]

        from src.models.data_container import DataContainer
        dc = DataContainer.model_validate(fake_docs[0])
        mock_find_many = AsyncMock(return_value=[dc])
        
        with patch("src.api.data_explorer.DataContainerRepository.find_many", mock_find_many):
            client = TestClient(app)
            response = client.get("/api/v1/data/transactions", params={"partner": "MOMO"})
            assert response.status_code == 200
            data = response.json()
            assert len(data["transactions"]) == 1
            assert data["transactions"][0]["identify"] == "MOMO"

    def test_invalid_date_returns_400(self):
        app, _, _ = _create_test_app()
        client = TestClient(app)
        response = client.get(
            "/api/v1/data/transactions",
            params={"date": "not-a-date"},
        )
        assert response.status_code == 400
        assert "Invalid date format" in response.json()["detail"]

    def test_limit_and_offset(self):
        app, mock_db, _ = _create_test_app()
        src_id = "550e8400-e29b-41d4-a716-446655440002"
        base_uuid = "550e8400-e29b-41d4-a716-44665544"
        req_id = "550e8400-e29b-41d4-a716-446655440001"
        fake_docs = [
            {"_id": f"{base_uuid}{i:04x}", "identify": "MOMO", "workflowType": "RECON",
             "reconciliationDate": "2024-07-07T00:00:00Z", "operationStatus": "DONE",
             "reconciliationStatus": "", "connectorData": "", "extraData": "",
             "sourceFileId": src_id,
             "partnerData": {"_id": "pd-1", "status": "SUCCESS", "amount": 100000, "currency": "VND"},
             "createdBy": "system", "createdDate": "2024-07-07T00:00:00Z",
             "lastModifiedBy": "system", "lastModifiedDate": "2024-07-07T00:00:00Z",
             "requestId": req_id}
            for i in range(5)
        ]

        from src.models.data_container import DataContainer
        dcs = [DataContainer.model_validate(doc) for doc in fake_docs]
        mock_find_many = AsyncMock(return_value=dcs)

        with patch("src.api.data_explorer.DataContainerRepository.find_many", mock_find_many):
            client = TestClient(app)
            response = client.get(
                "/api/v1/data/transactions",
                params={"limit": 2, "offset": 2},
            )
            assert response.status_code == 200
            assert len(response.json()["transactions"]) == 2


class TestGetTransaction:
    def test_existing_returns_record(self):
        app, mock_db, _ = _create_test_app()
        _id = "550e8400-e29b-41d4-a716-446655440000"
        src_id = "550e8400-e29b-41d4-a716-446655440002"
        req_id = "550e8400-e29b-41d4-a716-446655440001"
        doc = {
            "_id": _id, "identify": "MOMO", "workflowType": "RECON",
            "reconciliationDate": "2024-07-07T00:00:00Z", "operationStatus": "DONE",
            "reconciliationStatus": "", "connectorData": "", "extraData": "",
            "sourceFileId": src_id,
            "partnerData": {"_id": "pd-1", "status": "SUCCESS", "amount": 100000, "currency": "VND"},
            "createdBy": "system", "createdDate": "2024-07-07T00:00:00Z",
            "lastModifiedBy": "system", "lastModifiedDate": "2024-07-07T00:00:00Z",
            "requestId": req_id,
        }
        from src.models.data_container import DataContainer
        dc = DataContainer.model_validate(doc)
        mock_find_by_id = AsyncMock(return_value=dc)

        with patch("src.api.data_explorer.DataContainerRepository.find_by_id", mock_find_by_id):
            client = TestClient(app)
            response = client.get("/api/v1/data/transactions/" + _id)
            assert response.status_code == 200
            assert response.json()["_id"] == _id

    def test_non_existing_returns_404(self):
        app, mock_db, _ = _create_test_app()
        mock_find_by_id = AsyncMock(return_value=None)

        with patch("src.api.data_explorer.DataContainerRepository.find_by_id", mock_find_by_id):
            client = TestClient(app)
            response = client.get("/api/v1/data/transactions/nonexistent")
            assert response.status_code == 404
            assert "not found" in response.json()["detail"]


class TestListFiles:
    def test_returns_file_list(self):
        app, mock_db, _ = _create_test_app()
        mock_find_many = AsyncMock(return_value=[])

        with patch("src.api.data_explorer.ReconciliationFileRepository.find_many", mock_find_many):
            client = TestClient(app)
            response = client.get("/api/v1/data/files")
            assert response.status_code == 200
            assert "files" in response.json()


class TestGetFile:
    def test_returns_file_with_transaction_count(self):
        app, mock_db, _ = _create_test_app()
        file_id = "550e8400-e29b-41d4-a716-446655440001"
        mock_db.__getitem__.return_value.find_one = AsyncMock(return_value={
            "_id": file_id, "partner": "MOMO", "fileName": "test.xlsx",
            "fileHash": "abc123", "fileType": "EXCEL",
            "reconciliationDate": "2024-07-07T00:00:00Z",
            "processingStatus": "COMPLETED", "totalRows": 100,
            "successRows": 95, "failedRows": 5,
            "uploadedAt": "2024-07-07T00:00:00Z",
            "createdBy": "system", "createdAt": "2024-07-07T00:00:00Z",
        })
        mock_count = AsyncMock(return_value=50)

        with patch("src.api.data_explorer.DataContainerRepository.count_by_source_file", mock_count):
            client = TestClient(app)
            response = client.get("/api/v1/data/files/" + file_id)
            assert response.status_code == 200
            data = response.json()
            assert data["file"]["_id"] == file_id
            assert data["transactionCount"] == 50

    def test_non_existing_returns_404(self):
        app, mock_db, _ = _create_test_app()
        mock_db.__getitem__.return_value.find_one = AsyncMock(return_value=None)

        client = TestClient(app)
        response = client.get("/api/v1/data/files/nonexistent")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


class TestDataStats:
    def test_returns_aggregate_stats(self):
        app, mock_db, _ = _create_test_app()
        mock_db.__getitem__.return_value.count_documents = AsyncMock(return_value=500)
        mock_db.__getitem__.return_value.aggregate = MagicMock()

        with patch(
            "src.api.data_explorer.DataContainerRepository.count_by_partner",
            AsyncMock(return_value={"MOMO": 500}),
        ), patch(
            "src.api.data_explorer.DataContainerRepository.count",
            AsyncMock(return_value=500),
        ):
            client = TestClient(app)
            response = client.get("/api/v1/data/stats", params={"partner": "MOMO"})
        assert response.status_code == 200
        data = response.json()
        assert data["partner"] == "MOMO"
        assert "totalTransactions" in data
        assert "totalFiles" in data
        assert "byPartner" in data
