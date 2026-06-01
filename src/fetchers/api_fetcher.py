"""API fetcher for downloading partner data via HTTP APIs.

Supports GET/POST requests with custom headers, query params, and date interpolation.
Responses are saved as Excel/CSV files for ingestion.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

from src.fetchers.base import BaseFetcher, FetchResult
from src.models.fetch_config import APIConfig


class APIFetcher(BaseFetcher):
    """Fetches data from partner APIs.

    Uses httpx for async HTTP requests with retry logic and rate limiting.
    """

    MAX_RETRIES = 3
    BACKOFF_MULTIPLIER = 2
    INITIAL_BACKOFF = 1  # seconds

    async def fetch(
        self, config: APIConfig, reconciliation_date: datetime
    ) -> FetchResult:
        """Fetch data from partner API.

        Args:
            config: API configuration with base URL, headers, query params.
            reconciliation_date: Date for interpolating query params.

        Returns:
            FetchResult with local file path or error.
        """
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
            local_dir = Path("./downloads")
            local_dir.mkdir(parents=True, exist_ok=True)
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
                local_path.write_bytes(response.content)
            else:
                # Save as-is (likely Excel or CSV)
                local_path.write_bytes(response.content)

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
            )

        except ValueError as exc:
            # Credential resolution error
            return FetchResult(success=False, error=str(exc))
        except Exception as exc:
            return FetchResult(success=False, error=f"API fetch failed: {exc}")

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
                    return response

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exception = exc
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(backoff)
                    backoff *= self.BACKOFF_MULTIPLIER
                continue

        raise last_exception or httpx.HTTPError("All retries failed")
