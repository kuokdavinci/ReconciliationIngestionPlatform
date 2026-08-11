"""Contract tests for config-driven API pagination."""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.fetchers.api_fetcher import APIFetcher
from src.domain.fetch_config.models import APIConfig, APIPaginationConfig


def _response(payload, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.content = json.dumps(payload).encode("utf-8")
    response.text = response.content.decode("utf-8")
    response.headers = {"content-type": "application/json"}
    return response


def _config(download_dir):
    return APIConfig(
        base_url="https://api.example.com/transactions",
        method="GET",
        query_params={"date": "{date:%Y-%m-%d}"},
        download_dir=str(download_dir),
        pagination=APIPaginationConfig(
            page_param="page",
            cursor_param="cursor",
            page_size_param="limit",
            page_size=2,
            items_path="data.items",
            next_cursor_path="data.nextCursor",
        ),
    )


@pytest.mark.asyncio
async def test_fetch_pagination_persists_each_page_and_source_identity(tmp_path):
    config = _config(tmp_path)
    responses = [
        _response({"data": {"items": [{"id": 1}], "nextCursor": "cursor-1"}}),
        _response({"data": {"items": [{"id": 2}], "nextCursor": "cursor-2"}}),
        _response({"data": {"items": [{"id": 3}], "nextCursor": None}}),
    ]

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get.side_effect = responses
        result = await APIFetcher().fetch(config, datetime(2024, 7, 7))

    assert result.success is True
    assert len(result.units) == 3
    assert len({unit["sourceUnitKey"] for unit in result.units}) == 3
    assert len({unit["localPath"] for unit in result.units}) == 3
    assert result.units[0]["fetchMetadata"]["sampleRows"] == [{"id": 1}]
    assert result.metadata["pagination"]["items"] == [
        {"id": 1},
        {"id": 2},
        {"id": 3},
    ]
    assert result.metadata["pagination"]["next_cursor"] is None

    calls = mock_client.return_value.__aenter__.return_value.get.call_args_list
    assert calls[0].kwargs["params"] == {"date": "2024-07-07", "page": "1", "limit": "2"}
    assert calls[1].kwargs["params"]["cursor"] == "cursor-1"
    assert calls[2].kwargs["params"]["cursor"] == "cursor-2"


@pytest.mark.asyncio
async def test_empty_cursor_is_explicit_terminal_value(tmp_path):
    config = _config(tmp_path)
    responses = [
        _response({"data": {"items": [{"id": 1}], "nextCursor": ""}}),
    ]

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get.side_effect = responses
        result = await APIFetcher().fetch(config, datetime(2024, 7, 7))

    assert result.success is True
    assert result.metadata["pagination"]["has_more"] is False
    assert result.metadata["pagination"]["next_cursor"] == ""
    assert result.units[0]["cursorAfter"] == ""


@pytest.mark.asyncio
async def test_single_unit_mode_fetches_one_page_and_exposes_resume_cursor(tmp_path):
    config = _config(tmp_path)
    response = _response(
        {"data": {"items": [{"id": 1}], "nextCursor": "cursor-1"}}
    )

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get.return_value = response
        result = await APIFetcher().fetch(
            config,
            datetime(2024, 7, 7),
            fetch_metadata={"singleUnit": True},
        )

    assert result.success is True
    assert len(result.units) == 1
    assert result.units[0]["page"] == 1
    assert result.units[0]["cursorAfter"] == "cursor-1"
    assert result.metadata["pagination"] == {
        "items": [{"id": 1}],
        "has_more": True,
        "next_cursor": "cursor-1",
        "units": result.units,
        "source_identity": {
            "endpoint": config.base_url,
            "method": "GET",
            "reconciliationDate": "2024-07-07",
        },
    }
    assert mock_client.return_value.__aenter__.return_value.get.call_count == 1


@pytest.mark.asyncio
async def test_pagination_parse_failure_returns_failed_unit_without_success(tmp_path):
    config = _config(tmp_path)
    responses = [
        _response({"data": {"items": [{"id": 1}], "nextCursor": "cursor-1"}}),
        _response({"data": {"items": "not-a-list", "nextCursor": None}}),
    ]

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get.side_effect = responses
        result = await APIFetcher().fetch(config, datetime(2024, 7, 7))

    assert result.success is False
    assert [unit["status"] for unit in result.units] == ["FETCHED", "FAILED"]
    assert "items path must resolve to a list" in result.error


@pytest.mark.asyncio
async def test_http_5xx_is_retried_before_success(tmp_path):
    config = _config(tmp_path)
    responses = [
        _response({}, status_code=503),
        _response({}, status_code=502),
        _response({"data": {"items": [], "nextCursor": None}}),
    ]
    fetcher = APIFetcher()
    fetcher.INITIAL_BACKOFF = 0

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get.side_effect = responses
        result = await fetcher.fetch(config, datetime(2024, 7, 7))

    assert result.success is True
    assert mock_client.return_value.__aenter__.return_value.get.call_count == 3


@pytest.mark.asyncio
async def test_network_failure_returns_a_failed_source_unit_with_retry_code(tmp_path):
    config = _config(tmp_path)
    fetcher = APIFetcher()
    fetcher.INITIAL_BACKOFF = 0

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get.side_effect = httpx.NetworkError(
            "connection reset"
        )
        result = await fetcher.fetch(config, datetime(2024, 7, 7), fetch_metadata={"singleUnit": True})

    assert result.success is False
    assert result.units[-1]["status"] == "FAILED"
    assert result.units[-1]["errorCode"] == "fetch_network_error"


@pytest.mark.asyncio
async def test_parse_failure_is_terminal(tmp_path):
    config = _config(tmp_path)
    response = _response({"data": {"items": "not-a-list", "nextCursor": None}})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get.return_value = response
        result = await APIFetcher().fetch(
            config, datetime(2024, 7, 7), fetch_metadata={"singleUnit": True}
        )

    assert result.success is False
    assert result.units[-1]["errorCode"] == "pagination_parse_error"


@pytest.mark.asyncio
async def test_source_unit_identity_changes_with_config_version(tmp_path):
    config = _config(tmp_path)
    response = _response({"data": {"items": [], "nextCursor": None}})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get.return_value = response
        first = await APIFetcher().fetch(
            config,
            datetime(2024, 7, 7),
            fetch_metadata={"singleUnit": True, "configVersion": "v1"},
        )
        second = await APIFetcher().fetch(
            config,
            datetime(2024, 7, 7),
            fetch_metadata={"singleUnit": True, "configVersion": "v2"},
        )

    assert first.units[0].source_unit_key != second.units[0].source_unit_key
