"""Contract tests for config-driven API pagination."""

import json
from datetime import datetime
from pathlib import Path
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


def test_build_page_request_preserves_identity_filename_and_empty_cursor(tmp_path):
    config = _config(tmp_path)
    reconciliation_date = datetime(2024, 7, 7)

    query_params, local_path, unit = APIFetcher._build_page_request(
        config=config,
        reconciliation_date=reconciliation_date,
        base_query_params={"date": "2024-07-07"},
        local_dir=tmp_path,
        page=3,
        cursor="",
        config_version="v7",
    )

    assert query_params == {
        "date": "2024-07-07",
        "page": "3",
        "limit": "2",
        "cursor": "",
    }
    assert local_path == tmp_path / "api_data_20240707_page_0003.json"
    assert unit.page == 3
    assert unit.cursor_before == ""
    assert unit.source_identity == {
        "endpoint": config.base_url,
        "method": "GET",
        "reconciliationDate": "2024-07-07",
        "page": 3,
        "cursorBefore": "",
        "configVersion": "v7",
    }
    assert unit.source_unit_key == APIFetcher._source_unit_key(
        config.base_url,
        config.method,
        reconciliation_date,
        page=3,
        cursor_before="",
        config_version="v7",
    )


def test_parse_page_payload_returns_items_and_normalized_cursor():
    items, next_cursor = APIFetcher._parse_page_payload(
        json.dumps({"data": {"items": [{"id": 1}], "nextCursor": 42}}).encode("utf-8"),
        items_path="data.items",
        next_cursor_path="data.nextCursor",
    )

    assert items == [{"id": 1}]
    assert next_cursor == "42"


@pytest.mark.parametrize(
    ("payload", "expected_message"),
    [
        ({"data": {"items": "not-a-list", "nextCursor": None}}, "items path must resolve to a list"),
        (
            {"data": {"items": [], "nextCursor": {"cursor": "bad"}}},
            "next cursor must be a string, integer, null, or absent",
        ),
    ],
)
def test_parse_page_payload_rejects_invalid_items_and_cursor(payload, expected_message):
    with pytest.raises(ValueError, match=expected_message):
        APIFetcher._parse_page_payload(
            json.dumps(payload).encode("utf-8"),
            items_path="data.items",
            next_cursor_path="data.nextCursor",
        )


def test_write_page_returns_content_type_and_persists_exact_bytes(tmp_path):
    local_path = tmp_path / "page.json"
    response = httpx.Response(
        200,
        content=b'{"items":[1,2,3]}',
        headers={"content-type": "application/vnd.api+json"},
    )

    content_type = APIFetcher._write_page(response, local_path)

    assert content_type == "application/vnd.api+json"
    assert local_path.read_bytes() == b'{"items":[1,2,3]}'


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
async def test_storage_permission_failure_is_terminal_and_preserves_source_unit(tmp_path):
    config = _config(tmp_path)
    response = _response({"data": {"items": [{"id": 1}], "nextCursor": None}})

    with (
        patch("httpx.AsyncClient") as mock_client,
        patch.object(
            Path,
            "write_bytes",
            side_effect=PermissionError(13, "Permission denied"),
        ),
    ):
        mock_client.return_value.__aenter__.return_value.get.return_value = response
        result = await APIFetcher().fetch(
            config, datetime(2024, 7, 7), fetch_metadata={"singleUnit": True}
        )

    assert result.success is False
    assert result.metadata["errorCode"] == "fetch_storage_permission_denied"
    assert result.units[-1]["errorCode"] == "fetch_storage_permission_denied"
    assert result.units[-1]["status"] == "FAILED"


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
