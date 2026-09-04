"""Failure payload construction for source stream execution."""

from collections.abc import Callable
from typing import Any

from src.core.utils import sanitize_runtime_error, summarize_runtime_error


def fetch_error_code(error: str | None, metadata: dict[str, Any] | None = None) -> str:
    """Preserve the existing HTTP/network fetch error classification."""

    metadata = metadata or {}
    if metadata.get("errorCode"):
        return str(metadata["errorCode"])
    if "status 4" in (error or ""):
        return "fetch_http_4xx"
    if "status 5" in (error or ""):
        return "fetch_http_5xx"
    return "fetch_network_error"


def paginated_fetch_failure_result(
    *,
    error: str,
    error_code: str,
    fetched_unit_count: int,
    total_unit_count: int,
    current_page: int | None = None,
    stopped_at: str | None = None,
    include_unit_fields: bool = False,
    retryable: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "success": False,
        "processed": 0,
        "failed": 1,
        "fetchedUnitCount": fetched_unit_count,
        "totalUnitCount": total_unit_count,
    }
    if include_unit_fields:
        result["currentPage"] = current_page
        result["stoppedAt"] = stopped_at
    result.update(
        {
            "error": sanitize_runtime_error(error),
            "errorCode": sanitize_runtime_error(error_code, max_length=96),
            "retryable": retryable,
        }
    )
    return result


def file_fetch_failure_result(error: str | None) -> dict[str, Any]:
    """Return the legacy non-paginated fetch failure shape."""

    return {
        "success": False,
        "processed": 0,
        "failed": 1,
        "error": sanitize_runtime_error(error),
        "errorCode": "file_fetch_error",
    }


def unexpected_failure_result(
    exc: Exception,
    *,
    summarize_error: Callable[[Exception], str] = summarize_runtime_error,
) -> dict[str, Any]:
    return {
        "success": False,
        "processed": 0,
        "failed": 1,
        "error": sanitize_runtime_error(summarize_error(exc)),
    }


__all__ = [
    "fetch_error_code",
    "file_fetch_failure_result",
    "paginated_fetch_failure_result",
    "unexpected_failure_result",
]
