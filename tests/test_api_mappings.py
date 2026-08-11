"""Tests for Mapping Config API endpoint."""

from unittest.mock import MagicMock

from tests.asgi_test_client import TestClient


def _create_test_app():
    from fastapi import FastAPI
    from src.api.mappings import router

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


class TestListMappings:
    """Tests for GET /api/v1/mappings."""

    def test_list_all_mappings(self):
        """Returns all mapping configs when no partner filter."""
        app, mock_collection = _create_test_app()
        fake_configs = [
            {
                "_id": "cfg-001",
                "partner": "MOMO",
                "workflowType": "UPC",
                "fileType": "SETTLEMENT",
                "sheetName": "Sheet1",
                "startRow": 2,
                "fieldMappings": [
                    {"path": "id", "column": "A", "type": "STRING", "required": True},
                    {"path": "amount", "column": "D", "type": "DECIMAL"},
                ],
                "configVersion": "v1",
                "createdAt": "2024-01-01T00:00:00",
            },
            {
                "_id": "cfg-002",
                "partner": "ZALOPAY",
                "workflowType": "UPC",
                "fileType": "SETTLEMENT",
                "sheetName": "Data",
                "startRow": 3,
                "fieldMappings": [
                    {"path": "id", "column": "A", "type": "STRING", "required": True},
                ],
                "configVersion": "v2",
                "createdAt": "2024-01-02T00:00:00",
            },
        ]
        mock_cursor = _AsyncCursor(fake_configs)
        mock_collection.find = MagicMock(return_value=mock_cursor)

        client = TestClient(app)
        response = client.get("/api/v1/mappings")

        assert response.status_code == 200
        data = response.json()
        assert "mappings" in data
        assert len(data["mappings"]) == 2
        # Verify key fields from D-09
        mapping = data["mappings"][0]
        assert mapping["configVersion"] == "v1"
        assert mapping["partner"] == "MOMO"
        assert mapping["fileType"] == "SETTLEMENT"
        assert mapping["sheetName"] == "Sheet1"
        assert mapping["startRow"] == 2
        assert len(mapping["fieldMappings"]) == 2

    def test_list_mappings_with_partner_filter(self):
        """Filters mappings by partner when ?partner= is provided."""
        app, mock_collection = _create_test_app()
        # Mock find to return filtered results
        filtered_docs = [
            {
                "_id": "cfg-001",
                "partner": "MOMO",
                "workflowType": "UPC",
                "fileType": "SETTLEMENT",
                "sheetName": "Sheet1",
                "startRow": 2,
                "fieldMappings": [],
                "configVersion": "v1",
                "createdAt": "2024-01-01T00:00:00",
            },
        ]
        mock_cursor = _AsyncCursor(filtered_docs)
        mock_collection.find = MagicMock(return_value=mock_cursor)

        client = TestClient(app)
        response = client.get("/api/v1/mappings", params={"partner": "MOMO"})

        assert response.status_code == 200
        data = response.json()
        assert len(data["mappings"]) == 1
        assert data["mappings"][0]["partner"] == "MOMO"
        # Verify the query was filtered
        mock_collection.find.assert_called_once_with({"partner": "MOMO"})

    def test_empty_mappings_returns_empty_list(self):
        """Returns empty mappings array when no configs exist."""
        app, mock_collection = _create_test_app()
        mock_cursor = _AsyncCursor([])
        mock_collection.find = MagicMock(return_value=mock_cursor)

        client = TestClient(app)
        response = client.get("/api/v1/mappings")

        assert response.status_code == 200
        data = response.json()
        assert data["mappings"] == []

    def test_missing_db_returns_503(self):
        """Returns 503 when database connection is not available."""
        app, _ = _create_test_app()
        app.state.db = None

        client = TestClient(app)
        response = client.get("/api/v1/mappings")

        assert response.status_code == 503
        assert "Database connection not available" in response.json()["detail"]

    def test_empty_partner_returns_400(self):
        """Returns 400 when partner parameter is empty string."""
        app, _ = _create_test_app()
        client = TestClient(app)
        response = client.get("/api/v1/mappings", params={"partner": ""})

        assert response.status_code == 400
        assert "cannot be empty" in response.json()["detail"]

    def test_returns_500_on_db_error(self):
        """Returns 500 when database operation fails."""
        app, mock_collection = _create_test_app()
        mock_collection.find = MagicMock(side_effect=RuntimeError("DB connection lost"))

        client = TestClient(app)
        response = client.get("/api/v1/mappings")

        assert response.status_code == 500
        assert "Failed to list mappings" in response.json()["detail"]
