"""API fetcher for downloading partner data via HTTP APIs.

Supports GET/POST requests with custom headers, query params, and date interpolation.
Responses are saved as Excel/CSV files for ingestion.
"""

import asyncio
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx

from src.fetchers.base import BaseFetcher, FetchResult
from src.domain.fetch_config.models import APIConfig
from src.domain.ingestion.source_units import SourceUnitMetadata


class APIFetcher(BaseFetcher):
    """Fetches data from partner APIs.

    Uses httpx for async HTTP requests with retry logic and rate limiting.
    """

    MAX_RETRIES = 3
    BACKOFF_MULTIPLIER = 2
    INITIAL_BACKOFF = 1  # seconds
    REVIEW_SAMPLE_LIMIT = 100

    async def fetch(
        self,
        config: APIConfig,
        reconciliation_date: datetime,
        fetch_metadata: Optional[dict[str, Any]] = None,
    ) -> FetchResult:
        """Fetch data from partner API.

        Args:
            config: API configuration with base URL, headers, query params.
            reconciliation_date: Date for interpolating query params.

        Returns:
            FetchResult with local file path or error.
        """
        fetch_metadata = fetch_metadata or {}
        config_version = fetch_metadata.get("configVersion")
        try:
            # Resolve credentials in headers
            headers = {}
            if config.headers:
                for key, value in config.headers.items():
                    headers[key] = self.resolve_credential(value)

            # Interpolate date in query params
            query_params = {}
            if config.query_params:
                for key, value in config.query_params.items():
                    query_params[key] = self.interpolate_date(
                        value, reconciliation_date
                    )

            # Create local download directory
            download_dir = config.download_dir or "./downloads"
            local_dir = self.resolve_local_path(download_dir)
            try:
                local_dir.mkdir(parents=True, exist_ok=True)
            except PermissionError as exc:
                return FetchResult(
                    success=False,
                    error=f"API download path is not writable: {local_dir}: {exc}",
                    metadata={"errorCode": "fetch_storage_permission_denied"},
                )

            if config.pagination:
                return await self._fetch_paginated(
                    config,
                    reconciliation_date,
                    headers,
                    query_params,
                    local_dir,
                    fetch_metadata,
                )

            local_filename = f"api_data_{reconciliation_date.strftime('%Y%m%d')}.xlsx"
            local_path = local_dir / local_filename

            # Make API request with retry logic
            response = await self._request_with_retry(
                config.base_url,
                config.method,
                headers,
                query_params,
                config.timeout,
            )

            if response.status_code != 200:
                return FetchResult(
                    success=False,
                    error=f"API returned status {response.status_code}: {response.text[:200]}",
                )

            # Save response to file
            content_type = response.headers.get("content-type", "")
            if "json" in content_type:
                # Convert JSON to Excel (simplified - just save as JSON for now)
                local_path = local_path.with_suffix(".json")
                try:
                    local_path.write_bytes(response.content)
                except PermissionError as exc:
                    return FetchResult(
                        success=False,
                        local_path=str(local_path),
                        error=f"API download path is not writable: {local_path.parent}: {exc}",
                        metadata={"errorCode": "fetch_storage_permission_denied"},
                    )
            else:
                # Save as-is (likely Excel or CSV)
                try:
                    local_path.write_bytes(response.content)
                except PermissionError as exc:
                    return FetchResult(
                        success=False,
                        local_path=str(local_path),
                        error=f"API download path is not writable: {local_path.parent}: {exc}",
                        metadata={"errorCode": "fetch_storage_permission_denied"},
                    )

            # Validate downloaded file
            if not self.validate_file(str(local_path)):
                return FetchResult(
                    success=False,
                    error=f"Downloaded file is empty or missing: {local_path}",
                )

            file_size = local_path.stat().st_size

            return FetchResult(
                success=True,
                local_path=str(local_path),
                file_size=file_size,
                metadata={
                    "url": config.base_url,
                    "status_code": response.status_code,
                    "content_type": content_type,
                },
                units=[
                    SourceUnitMetadata(
                        sourceUnitKey=self._source_unit_key(
                            config.base_url,
                            config.method,
                            reconciliation_date,
                            page=None,
                            cursor_before=None,
                            config_version=config_version,
                        ),
                        localPath=str(local_path),
                        sourceIdentity={
                            "endpoint": config.base_url,
                            "method": config.method.upper(),
                            "reconciliationDate": reconciliation_date.strftime(
                                "%Y-%m-%d"
                            ),
                            **(
                                {"configVersion": config_version}
                                if config_version
                                else {}
                            ),
                        },
                        status="FETCHED",
                    )
                ],
            )

        except ValueError as exc:
            # Credential resolution error
            return FetchResult(success=False, error=str(exc))
        except Exception as exc:
            return FetchResult(success=False, error=f"API fetch failed: {exc}")

    async def _fetch_paginated(
        self,
        config: APIConfig,
        reconciliation_date: datetime,
        headers: dict[str, str],
        base_query_params: dict[str, str],
        local_dir: Path,
        fetch_metadata: dict[str, Any],
    ) -> FetchResult:
        """Fetch and persist each API page as an independently identified unit."""
        pagination = config.pagination
        assert pagination is not None
        config_version = fetch_metadata.get("configVersion")

        page = self._starting_page(fetch_metadata)
        cursor = fetch_metadata.get("cursor")
        units: list[SourceUnitMetadata] = []
        items: list[Any] = []
        seen_cursors: set[str] = set()
        final_cursor: Optional[str] = None

        for _ in range(pagination.max_pages):
            query_params = dict(base_query_params)
            if pagination.page_param:
                query_params[pagination.page_param] = str(page)
            if pagination.page_size_param and pagination.page_size is not None:
                query_params[pagination.page_size_param] = str(pagination.page_size)
            if pagination.cursor_param and cursor is not None:
                # An empty cursor is intentional and must not be treated as absent.
                query_params[pagination.cursor_param] = str(cursor)

            source_identity = {
                "endpoint": config.base_url,
                "method": config.method.upper(),
                "reconciliationDate": reconciliation_date.strftime("%Y-%m-%d"),
                "page": page,
                "cursorBefore": cursor,
                **(
                    {"configVersion": config_version}
                    if config_version
                    else {}
                ),
            }
            local_path = local_dir / (
                f"api_data_{reconciliation_date.strftime('%Y%m%d')}"
                f"_page_{page:04d}.json"
            )
            source_unit_key = self._source_unit_key(
                config.base_url,
                config.method,
                reconciliation_date,
                page=page,
                cursor_before=cursor,
                config_version=config_version,
            )
            unit = SourceUnitMetadata(
                sourceUnitKey=source_unit_key,
                sourceIdentity=source_identity,
                localPath=str(local_path),
                page=page,
                cursorBefore=cursor,
            )

            try:
                response = await self._request_with_retry(
                    config.base_url,
                    config.method,
                    headers,
                    query_params,
                    config.timeout,
                )
            except Exception as exc:
                unit.status = "FAILED"
                unit.error = f"API pagination request failed: {exc}"
                unit.error_code = (
                    "fetch_timeout"
                    if isinstance(exc, httpx.TimeoutException)
                    else "fetch_network_error"
                )
                units.append(unit)
                return FetchResult(
                    success=False,
                    error=unit.error,
                    metadata={"pagination": {"units": units}},
                    units=units,
                )

            content_type = response.headers.get("content-type", "")
            try:
                local_path.write_bytes(response.content)
            except PermissionError as exc:
                unit.status = "FAILED"
                unit.error = f"API download path is not writable: {local_path.parent}"
                unit.error_code = "fetch_storage_permission_denied"
                units.append(unit)
                return FetchResult(
                    success=False,
                    local_path=str(local_path),
                    error=f"{unit.error}: {exc}",
                    metadata={
                        "errorCode": unit.error_code,
                        "pagination": {"units": units},
                    },
                    units=units,
                )
            unit.content_hash = hashlib.sha256(response.content).hexdigest()
            unit.status_code = response.status_code
            unit.content_type = content_type

            if not 200 <= response.status_code < 300:
                unit.status = "FAILED"
                unit.error = f"API returned status {response.status_code}"
                unit.error_code = (
                    "fetch_http_4xx"
                    if 400 <= response.status_code < 500
                    else "fetch_http_5xx"
                )
                units.append(unit)
                return FetchResult(
                    success=False,
                    local_path=str(units[0]["localPath"]) if units else None,
                    error=f"API returned status {response.status_code}: {response.text[:200]}",
                    metadata={"pagination": {"units": units}},
                    units=units,
                )

            try:
                payload = json.loads(response.content.decode("utf-8"))
                page_items = self._extract_pagination_value(
                    payload, pagination.items_path
                )
                if not isinstance(page_items, list):
                    raise ValueError("items path must resolve to a list")
                next_cursor_value = self._extract_pagination_value(
                    payload, pagination.next_cursor_path
                )
                if next_cursor_value is not None and not isinstance(
                    next_cursor_value, (str, int)
                ):
                    raise ValueError("next cursor must be a string, integer, null, or absent")
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
                unit.status = "FAILED"
                unit.error = f"pagination response parse failed: {exc}"
                unit.error_code = "pagination_parse_error"
                units.append(unit)
                return FetchResult(
                    success=False,
                    local_path=str(units[0]["localPath"]) if units else None,
                    error=unit["error"],
                    metadata={"pagination": {"units": units}},
                    units=units,
                )

            next_cursor = (
                None
                if next_cursor_value is None
                else str(next_cursor_value)
            )
            has_more = next_cursor is not None and next_cursor != ""
            unit.status = "FETCHED"
            unit.item_count = len(page_items)
            unit.cursor_after = next_cursor
            unit.has_more = has_more
            # Keep a bounded, source-side sample with the claim metadata. The
            # downloaded file may be cleaned up before a later page triggers a
            # mapping review, but the review packet still needs all pages that
            # were already fetched.
            unit.fetch_metadata = {
                "sampleRows": page_items[: self.REVIEW_SAMPLE_LIMIT]
            }
            units.append(unit)
            items.extend(page_items)
            final_cursor = next_cursor

            if fetch_metadata.get("singleUnit") or fetch_metadata.get("single_unit"):
                return FetchResult(
                    success=True,
                    local_path=str(local_path),
                    file_size=local_path.stat().st_size,
                    metadata={
                        "url": config.base_url,
                        "status_code": response.status_code,
                        "content_type": content_type,
                        "pagination": {
                            "items": page_items,
                            "has_more": has_more,
                            "next_cursor": next_cursor,
                            "units": units,
                            "source_identity": {
                                "endpoint": config.base_url,
                                "method": config.method.upper(),
                                "reconciliationDate": reconciliation_date.strftime(
                                    "%Y-%m-%d"
                                ),
                            },
                        },
                    },
                    units=units,
                )

            if not has_more:
                first_path = str(units[0]["localPath"])
                return FetchResult(
                    success=True,
                    local_path=first_path,
                    file_size=sum(
                        Path(item["localPath"]).stat().st_size for item in units
                    ),
                    metadata={
                        "url": config.base_url,
                        "status_code": response.status_code,
                        "content_type": content_type,
                        "pagination": {
                            "items": items,
                            "has_more": False,
                            "next_cursor": final_cursor,
                            "units": units,
                            "source_identity": {
                                "endpoint": config.base_url,
                                "method": config.method.upper(),
                                "reconciliationDate": reconciliation_date.strftime(
                                    "%Y-%m-%d"
                                ),
                            },
                        },
                    },
                    units=units,
                )

            cursor_marker = json.dumps(next_cursor, sort_keys=True)
            if cursor_marker in seen_cursors:
                unit.status = "FAILED"
                unit.error = "pagination returned a repeated cursor"
                unit.error_code = "pagination_cursor_repeated"
                return FetchResult(
                    success=False,
                    local_path=str(units[0]["localPath"]),
                    error=unit["error"],
                    metadata={"pagination": {"units": units}},
                    units=units,
                )
            seen_cursors.add(cursor_marker)
            cursor = next_cursor
            page += 1

        return FetchResult(
            success=False,
            local_path=str(units[0]["localPath"]) if units else None,
            error=f"pagination exceeded max pages ({pagination.max_pages})",
            metadata={"pagination": {"units": units}},
            units=units,
        )

    @staticmethod
    def _starting_page(fetch_metadata: dict[str, Any]) -> int:
        page = fetch_metadata.get("page", 1)
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise ValueError("pagination page must be a positive integer")
        return page

    @staticmethod
    def _extract_pagination_value(payload: Any, path: Optional[str]) -> Any:
        """Resolve a dotted JSON path while preserving missing vs empty values."""
        if not path:
            if isinstance(payload, dict) and "items" in payload:
                return payload["items"]
            return payload if isinstance(payload, list) else None

        current = payload
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

    @staticmethod
    def _source_unit_key(
        endpoint: str,
        method: str,
        reconciliation_date: datetime,
        page: Optional[int],
        cursor_before: Optional[Any],
        config_version: Optional[str] = None,
    ) -> str:
        identity = {
            "endpoint": endpoint,
            "method": method.upper(),
            "reconciliationDate": reconciliation_date.strftime("%Y-%m-%d"),
            "page": page,
            "cursorBefore": cursor_before,
            "configVersion": config_version,
        }
        return hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    async def _request_with_retry(
        self,
        url: str,
        method: str,
        headers: dict,
        query_params: dict,
        timeout: int,
    ) -> httpx.Response:
        """Make HTTP request with exponential backoff retry.

        Args:
            url: Request URL.
            method: HTTP method (GET/POST).
            headers: Request headers.
            query_params: Query parameters.
            timeout: Request timeout in seconds.

        Returns:
            HTTP response.

        Raises:
            httpx.HTTPError: If all retries fail.
        """
        last_exception = None
        backoff = self.INITIAL_BACKOFF

        for attempt in range(self.MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    if method.upper() == "POST":
                        response = await client.post(
                            url, headers=headers, params=query_params
                        )
                    else:
                        response = await client.get(
                            url, headers=headers, params=query_params
                        )
                    if response.status_code >= 500 and attempt < self.MAX_RETRIES - 1:
                        await asyncio.sleep(backoff)
                        backoff *= self.BACKOFF_MULTIPLIER
                        continue
                    return response

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exception = exc
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(backoff)
                    backoff *= self.BACKOFF_MULTIPLIER
                continue

        raise last_exception or httpx.HTTPError("All retries failed")
