"""Tests for FastAPI insights endpoints.

Uses FastAPI TestClient with mocked orchestration layer to verify:
- Request validation (date format, partner required)
- Endpoint responses (summary, discrepancies, daily report)
- Error handling (400, 500 responses)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.analysis.schemas import AnalysisResult


# ---------------------------------------------------------------------------
# Test fixtures and helpers
# ---------------------------------------------------------------------------

def _create_test_app() -> "FastAPI":
    """Create a FastAPI app with mocked dependencies for testing."""
    from fastapi import FastAPI
    from src.api.insights import router as insights_router

    app = FastAPI()
    app.include_router(insights_router)

    # Mock db in app state
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    app.state.db = mock_db
    app.state.mongo_client = MagicMock()

    return app


def _make_mock_cursor(docs: list[dict]) -> AsyncMock:
    """Create a mock MongoDB cursor."""
    mock_cursor = AsyncMock()
    mock_cursor.to_list = AsyncMock(return_value=docs)
    return mock_cursor


class MockLLMProvider:
    """Mock LLM provider for testing."""

    def __init__(self, response: str = "", should_fail: bool = False):
        self._response = response
        self._should_fail = should_fail
        self.call_count = 0

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        self.call_count += 1
        if self._should_fail:
            raise RuntimeError("LLM call failed")
        return self._response

    @property
    def model(self) -> str:
        return "test-model"

    @property
    def provider_name(self) -> str:
        return "test"

    @property
    def last_token_usage(self) -> dict[str, int] | None:
        return None


# ---------------------------------------------------------------------------
# GET /api/v1/insights/summary tests
# ---------------------------------------------------------------------------

class TestInsightsSummary:
    """Test GET /api/v1/insights/summary endpoint."""

    def test_requires_partner_parameter(self) -> None:
        app = _create_test_app()
        client = TestClient(app)

        response = client.get("/api/v1/insights/summary", params={"date": "2024-07-07"})

        assert response.status_code == 400
        assert "Partner identifier is required" in response.json()["detail"]

    def test_requires_date_parameter(self) -> None:
        app = _create_test_app()
        client = TestClient(app)

        response = client.get("/api/v1/insights/summary", params={"partner": "MOMO"})

        assert response.status_code == 400
        assert "Date parameter is required" in response.json()["detail"]

    def test_validates_date_format(self) -> None:
        app = _create_test_app()
        client = TestClient(app)

        response = client.get(
            "/api/v1/insights/summary",
            params={"partner": "MOMO", "date": "invalid-date"},
        )

        assert response.status_code == 400
        assert "Invalid date format" in response.json()["detail"]

    def test_returns_summary_with_mocked_orchestration(self) -> None:
        app = _create_test_app()
        client = TestClient(app)

        # Mock the orchestration layer
        mock_summary_result = {
            "partner": "MOMO",
            "date": "2024-07-07",
            "summary_metrics": {
                "total_transactions": 100,
                "matched": 95,
                "mismatch_rate": 5.0,
                "total_amount_mismatch": 500000,
                "by_status": {"MATCHED": 95, "AMOUNT_MISMATCH": 5},
            },
            "grouped_stats": [
                {"key": "MATCHED", "count": 95, "percentage": 95.0, "total_amount": 9500000, "details": {}},
                {"key": "AMOUNT_MISMATCH", "count": 5, "percentage": 5.0, "total_amount": 500000, "details": {"avg_difference": 100000}},
            ],
            "key_findings": ["Mismatch rate: 5.0% (5 affected)"],
            "generated_at": "2024-07-07",
            "llm_status": "success",
        }

        with patch("src.analysis.insights.get_summary", new_callable=AsyncMock) as mock_get_summary:
            mock_get_summary.return_value = mock_summary_result

            with patch("src.api.insights._get_llm_provider", return_value=MockLLMProvider(response="{}")):
                response = client.get(
                    "/api/v1/insights/summary",
                    params={"partner": "MOMO", "date": "2024-07-07"},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["partner"] == "MOMO"
        assert data["date"] == "2024-07-07"
        assert data["summaryMetrics"]["totalTransactions"] == 100
        assert data["summaryMetrics"]["matched"] == 95
        assert data["summaryMetrics"]["mismatchRate"] == 5.0
        assert len(data["groupedStats"]) == 2
        assert len(data["keyFindings"]) == 1
        assert "T" in data["generatedAt"]

    def test_returns_500_on_orchestration_error(self) -> None:
        app = _create_test_app()
        client = TestClient(app)

        with patch("src.analysis.insights.get_summary", new_callable=AsyncMock) as mock_get_summary:
            mock_get_summary.side_effect = RuntimeError("Database connection failed")

            with patch("src.api.insights._get_llm_provider", return_value=MockLLMProvider(response="{}")):
                response = client.get(
                    "/api/v1/insights/summary",
                    params={"partner": "MOMO", "date": "2024-07-07"},
                )

        assert response.status_code == 500
        assert "Failed to generate summary insights" in response.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/v1/insights/discrepancies tests
# ---------------------------------------------------------------------------

class TestInsightsDiscrepancies:
    """Test GET /api/v1/insights/discrepancies endpoint."""

    def test_requires_partner_parameter(self) -> None:
        app = _create_test_app()
        client = TestClient(app)

        response = client.get(
            "/api/v1/insights/discrepancies",
            params={"date": "2024-07-07", "focus": "operational"},
        )

        assert response.status_code == 400
        assert "Partner identifier is required" in response.json()["detail"]

    def test_validates_date_format(self) -> None:
        app = _create_test_app()
        client = TestClient(app)

        response = client.get(
            "/api/v1/insights/discrepancies",
            params={"partner": "MOMO", "date": "bad-date", "focus": "operational"},
        )

        assert response.status_code == 400
        assert "Invalid date format" in response.json()["detail"]

    def test_validates_focus_parameter(self) -> None:
        app = _create_test_app()
        client = TestClient(app)

        response = client.get(
            "/api/v1/insights/discrepancies",
            params={"partner": "MOMO", "date": "2024-07-07", "focus": "invalid"},
        )

        assert response.status_code == 400
        assert "Invalid focus" in response.json()["detail"]

    def test_default_focus_is_operational(self) -> None:
        app = _create_test_app()
        client = TestClient(app)

        with patch("src.analysis.insights.get_discrepancies", new_callable=AsyncMock) as mock_get_disc:
            mock_get_disc.return_value = []

            with patch("src.api.insights._get_llm_provider", return_value=MockLLMProvider(response="{}")):
                response = client.get(
                    "/api/v1/insights/discrepancies",
                    params={"partner": "MOMO", "date": "2024-07-07"},
                )

        assert response.status_code == 200
        # Verify focus was passed as "operational" (default)
        call_kwargs = mock_get_disc.call_args
        assert call_kwargs[1]["focus"] == "operational"

    def test_returns_discrepancies_list(self) -> None:
        app = _create_test_app()
        client = TestClient(app)

        mock_results = [
            AnalysisResult(
                type="operational_delay",
                severity="medium",
                title="Delay detected",
                description="5 transactions missing internal",
                affected_count=5,
                recommendation="Check pipeline",
            )
        ]

        with patch("src.analysis.insights.get_discrepancies", new_callable=AsyncMock) as mock_get_disc:
            mock_get_disc.return_value = mock_results

            with patch("src.api.insights._get_llm_provider", return_value=MockLLMProvider(response="{}")):
                response = client.get(
                    "/api/v1/insights/discrepancies",
                    params={"partner": "MOMO", "date": "2024-07-07", "focus": "operational"},
                )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["type"] == "operational_delay"
        assert data[0]["severity"] == "medium"
        assert data[0]["affectedCount"] == 5

    def test_returns_500_on_orchestration_error(self) -> None:
        app = _create_test_app()
        client = TestClient(app)

        with patch("src.analysis.insights.get_discrepancies", new_callable=AsyncMock) as mock_get_disc:
            mock_get_disc.side_effect = RuntimeError("Connection failed")

            with patch("src.api.insights._get_llm_provider", return_value=MockLLMProvider(response="{}")):
                response = client.get(
                    "/api/v1/insights/discrepancies",
                    params={"partner": "MOMO", "date": "2024-07-07", "focus": "operational"},
                )

        assert response.status_code == 500
        assert "Failed to generate discrepancy insights" in response.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/v1/reports/daily tests
# ---------------------------------------------------------------------------

class TestReportsDaily:
    """Test GET /api/v1/reports/daily endpoint."""

    def test_requires_date_parameter(self) -> None:
        app = _create_test_app()
        client = TestClient(app)

        response = client.get("/api/v1/reports/daily")

        assert response.status_code == 400
        assert "Date parameter is required" in response.json()["detail"]

    def test_validates_date_format(self) -> None:
        app = _create_test_app()
        client = TestClient(app)

        response = client.get(
            "/api/v1/reports/daily",
            params={"date": "not-a-date"},
        )

        assert response.status_code == 400
        assert "Invalid date format" in response.json()["detail"]

    def test_returns_daily_report(self) -> None:
        app = _create_test_app()
        client = TestClient(app)

        mock_report = {
            "date": "2024-07-07",
            "generated_at": "2024-07-07",
            "partners": [
                {
                    "partner": "MOMO",
                    "summary_metrics": {"total_transactions": 100, "matched": 95, "mismatch_rate": 5.0},
                    "grouped_stats": [],
                    "key_findings": ["Test finding"],
                }
            ],
            "global_stats": {"total_mismatch_rate": 5.0, "total_volume": 10000000, "alert_count": 0},
        }

        with patch("src.analysis.reporter.DailyReporter") as MockReporter:
            mock_reporter_instance = MagicMock()
            mock_reporter_instance.generate_report = AsyncMock(return_value=mock_report)
            MockReporter.return_value = mock_reporter_instance

            with patch("src.analysis.alerter.ThresholdAlerter") as MockAlerter:
                mock_alerter_instance = MagicMock()
                mock_alerter_instance.alerts_for_report = MagicMock(return_value=[])
                MockAlerter.return_value = mock_alerter_instance

                with patch("src.api.insights._get_llm_provider", return_value=MockLLMProvider(response="{}")):
                    response = client.get(
                        "/api/v1/reports/daily",
                        params={"date": "2024-07-07"},
                    )

        assert response.status_code == 200
        data = response.json()
        assert data["date"] == "2024-07-07"
        assert len(data["partners"]) == 1
        assert data["partners"][0]["partner"] == "MOMO"
        assert "alerts" in data
        assert data["partners"][0]["summaryMetrics"]["totalTransactions"] == 100
        assert "generatedAt" in data
        assert "T" in data["generatedAt"]  # Proper ISO timestamp

    def test_returns_500_on_report_error(self) -> None:
        app = _create_test_app()
        client = TestClient(app)

        with patch("src.analysis.reporter.DailyReporter") as MockReporter:
            mock_reporter_instance = MagicMock()
            mock_reporter_instance.generate_report = AsyncMock(side_effect=RuntimeError("DB error"))
            MockReporter.return_value = mock_reporter_instance

            with patch("src.analysis.alerter.ThresholdAlerter") as MockAlerter:
                mock_alerter_instance = MagicMock()
                mock_alerter_instance.alerts_for_report = MagicMock(return_value=[])
                MockAlerter.return_value = mock_alerter_instance

                with patch("src.api.insights._get_llm_provider", return_value=MockLLMProvider(response="{}")):
                    response = client.get(
                        "/api/v1/reports/daily",
                        params={"date": "2024-07-07"},
                    )

        assert response.status_code == 500
        assert "Failed to generate daily report" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Request validation helper tests
# ---------------------------------------------------------------------------

class TestValidationHelpers:
    """Test request validation helper functions."""

    def test_validate_date_accepts_valid_format(self) -> None:
        from src.api.insights import _validate_date

        result = _validate_date("2024-07-07")
        assert result == "2024-07-07"

    def test_validate_date_rejects_invalid_format(self) -> None:
        from src.api.insights import _validate_date

        with pytest.raises(HTTPException) as exc_info:
            _validate_date("07-07-2024")

        assert exc_info.value.status_code == 400
        assert "Invalid date format" in str(exc_info.value.detail)

    def test_validate_partner_accepts_valid_partner(self) -> None:
        from src.api.insights import _validate_partner

        result = _validate_partner("MOMO")
        assert result == "MOMO"

    def test_validate_partner_strips_whitespace(self) -> None:
        from src.api.insights import _validate_partner

        result = _validate_partner("  MOMO  ")
        assert result == "MOMO"

    def test_validate_partner_rejects_empty(self) -> None:
        from src.api.insights import _validate_partner

        with pytest.raises(HTTPException) as exc_info:
            _validate_partner("")

        assert exc_info.value.status_code == 400
        assert "Partner identifier is required" in str(exc_info.value.detail)

    def test_validate_partner_rejects_none(self) -> None:
        from src.api.insights import _validate_partner

        with pytest.raises(HTTPException) as exc_info:
            _validate_partner(None)

        assert exc_info.value.status_code == 400
