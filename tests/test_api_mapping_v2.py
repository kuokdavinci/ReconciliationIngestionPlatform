"""Tests for Partner Mapping Studio v2 endpoints."""

from tests.asgi_test_client import TestClient
from unittest.mock import MagicMock, AsyncMock

def _create_test_app():
    from fastapi import FastAPI
    from src.api.mappings import router_v2

    app = FastAPI()
    app.include_router(router_v2)
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    app.state.db = mock_db
    app.state.mongo_client = MagicMock()
    return app, mock_collection

class _AsyncCursor:
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

def test_validate_mapping_valid():
    app, _ = _create_test_app()
    client = TestClient(app)
    payload = {
        "partner": "VNPAY",
        "workflowType": "UPC",
        "fileType": "SETTLEMENT",
        "sheetName": "Sheet1",
        "startRow": 2,
        "configVersion": "v1",
        "fieldMappings": [
            {"path": "id", "column": 1, "type": "STRING", "required": True},
            {"path": "amount", "column": 2, "type": "DECIMAL", "required": True},
            {"path": "transDate", "column": 3, "type": "DATE", "required": True},
            {"path": "status", "column": 4, "type": "STRING", "required": True}
        ]
    }
    response = client.post("/api/v1/mapping/validate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["score"] >= 90

def test_validate_mapping_missing_required():
    app, _ = _create_test_app()
    client = TestClient(app)
    payload = {
        "partner": "VNPAY",
        "workflowType": "UPC",
        "fileType": "SETTLEMENT",
        "sheetName": "Sheet1",
        "startRow": 2,
        "configVersion": "v1",
        "fieldMappings": [
            {"path": "id", "column": 1, "type": "STRING", "required": True}
        ]
    }
    response = client.post("/api/v1/mapping/validate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert any("amount" in err for err in data["errors"])

def test_test_mapping_transform():
    app, _ = _create_test_app()
    client = TestClient(app)
    payload = {
        "mapping": {
            "partner": "VNPAY",
            "workflowType": "UPC",
            "fileType": "SETTLEMENT",
            "sheetName": "Sheet1",
            "startRow": 2,
            "configVersion": "v1",
            "fieldMappings": [
                {"path": "id", "column": 1, "type": "STRING", "required": True},
                {"path": "amount", "column": 2, "type": "DECIMAL", "required": True},
                {"path": "currency", "constant": "VND", "type": "CONSTANT"}
            ]
        },
        "sampleRow": ["TXN001", "150000"]
    }
    response = client.post("/api/v1/mapping/test", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["output"]["id"] == "TXN001"
    assert float(data["output"]["amount"]) == 150000.0
    assert data["output"]["currency"] == "VND"

def test_publish_mapping():
    app, mock_collection = _create_test_app()
    client = TestClient(app)
    
    # Mock find_one to return None (no existing config)
    mock_collection.find_one = AsyncMock(return_value=None)
    mock_collection.insert_one = AsyncMock()
    
    # Mock history collection insert
    mock_history = MagicMock()
    mock_history.insert_one = AsyncMock()
    app.state.db.__getitem__ = MagicMock(side_effect=lambda name: mock_history if name == "reconciliation_mapping_config_history" else mock_collection)
    
    payload = {
        "partner": "VNPAY",
        "workflowType": "UPC",
        "fileType": "SETTLEMENT",
        "sheetName": "Sheet1",
        "startRow": 2,
        "configVersion": "v1",
        "fieldMappings": []
    }
    response = client.post("/api/v1/mapping/publish", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["version"] == "v1"

def test_list_versions():
    app, mock_collection = _create_test_app()
    client = TestClient(app)
    
    fake_versions = [
        {"_id": "v-001", "partner": "VNPAY", "configVersion": "v1", "publishedAt": "2024-01-01T00:00:00"}
    ]
    mock_cursor = _AsyncCursor(fake_versions)
    mock_history = MagicMock()
    mock_history.find = MagicMock(return_value=mock_history)
    mock_history.sort = MagicMock(return_value=mock_cursor)
    
    app.state.db.__getitem__ = MagicMock(side_effect=lambda name: mock_history if name == "reconciliation_mapping_config_history" else mock_collection)
    
    response = client.get("/api/v1/mapping/versions", params={"partner": "VNPAY"})
    assert response.status_code == 200
    data = response.json()
    assert len(data["versions"]) == 1
    assert data["versions"][0]["configVersion"] == "v1"

def test_get_version():
    app, mock_collection = _create_test_app()
    client = TestClient(app)
    
    fake_version = {"_id": "v-001", "partner": "VNPAY", "configVersion": "v1", "publishedAt": "2024-01-01T00:00:00"}
    mock_history = MagicMock()
    mock_history.find_one = AsyncMock(return_value=fake_version)
    
    app.state.db.__getitem__ = MagicMock(side_effect=lambda name: mock_history if name == "reconciliation_mapping_config_history" else mock_collection)
    
    response = client.get("/api/v1/mapping/version/v-001")
    assert response.status_code == 200
    data = response.json()
    assert data["configVersion"] == "v1"
