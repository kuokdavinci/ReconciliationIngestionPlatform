"""Structured JSON logger for the reconciliation ingestion platform.

Provides:
- LogEventType enum for file/row lifecycle events
- JSONFormatter and TextFormatter for configurable output
- StructuredLogger with per-row and per-file emit helpers
- Module-level singleton via get_structured_logger()
"""

import json
import logging
import re
import sys
import threading
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Optional

from src.config.settings import settings


class LogEventType(StrEnum):
    """Event types for structured logging."""

    FILE_STARTED = "FILE_STARTED"
    FILE_COMPLETED = "FILE_COMPLETED"
    FILE_FAILED = "FILE_FAILED"
    ROW_SUCCESS = "ROW_SUCCESS"
    ROW_FAILED = "ROW_FAILED"
    INGESTION_STAGE = "INGESTION_STAGE"
    INGESTION_OBSERVABILITY_WRITE_FAILED = "INGESTION_OBSERVABILITY_WRITE_FAILED"


# Internal logging fields to exclude from JSON output
_INTERNAL_FIELDS = frozenset({
    "name", "msg", "args", "created", "relativeCreated",
    "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "pathname", "filename", "module", "msecs", "process",
    "processName", "thread", "threadName", "taskName",
})

# Maximum length for sanitized log field values (T-07-01 mitigation)
_MAX_FIELD_LENGTH = 256


_SENSITIVE_KEY = re.compile(
    r"(?i)(password|passwd|token|secret|api[_-]?key|authorization|credential|fingerprint)"
)
_SENSITIVE_VALUE = re.compile(
    r"(?i)\b(password|passwd|token|secret|api[_-]?key|authorization|credential|fingerprint)\b"
    r"\s*[:=]\s*(?:bearer\s+)?[^\s,;]+"
)
_CREDENTIAL_URL = re.compile(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@")


def _sanitize(value: Any, *, key: str | None = None) -> Any:
    """Bound and redact structured values before they reach a log handler."""
    if key and _SENSITIVE_KEY.search(str(key)):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _sanitize(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, (int, float, bool, type(None))):
        return value
    text = _CREDENTIAL_URL.sub(r"\1[REDACTED]@", str(value))
    text = _SENSITIVE_VALUE.sub(r"\1=[REDACTED]", text)
    if len(text) > _MAX_FIELD_LENGTH:
        return text[:_MAX_FIELD_LENGTH] + "..."
    return text


def _default_serializer(obj: Any) -> Any:
    """JSON serializer fallback for Decimal, datetime, etc."""
    if hasattr(obj, "__str__"):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class JSONFormatter(logging.Formatter):
    """Formatter that outputs one JSON object per log line.

    Includes: timestamp (ISO 8601), level, event, message, and all extra fields.
    Filters out internal logging._record fields.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as a JSON string."""
        log_data: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", record.msg),
            "message": _sanitize(record.getMessage(), key="message"),
        }

        # Add extra fields (excluding internal logging fields)
        for key, value in record.__dict__.items():
            if key not in _INTERNAL_FIELDS and key not in log_data:
                log_data[key] = _sanitize(value, key=key)

        return json.dumps(log_data, default=_default_serializer)


class TextFormatter(logging.Formatter):
    """Formatter that outputs human-readable log lines.

    Format: "[LEVEL] {event}: {message} {extra_fields as key=value}"
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as a human-readable string."""
        event = getattr(record, "event", record.msg)
        parts = [
            f"[{record.levelname}] {event}: "
            f"{_sanitize(record.getMessage(), key='message')}"
        ]

        # Add extra fields as key=value pairs
        for key, value in sorted(record.__dict__.items()):
            if key not in _INTERNAL_FIELDS and key not in ("event",):
                parts.append(f"{key}={_sanitize(value, key=key)}")

        return " ".join(parts)


class StructuredLogger:
    """Wrapper around Python's logging.Logger with structured event emission.

    Configured via settings.log_level and settings.log_format.
    Provides typed emit methods for file lifecycle and per-row events.
    """

    def __init__(self, name: str = "reconciliation") -> None:
        self._logger = logging.getLogger(name)
        self._setup_handler()

    def _setup_handler(self) -> None:
        """Configure handler with formatter based on settings."""
        # Remove existing handlers to avoid duplicates
        self._logger.handlers.clear()

        handler = logging.StreamHandler(sys.stdout)

        if settings.log_format == "json":
            handler.setFormatter(JSONFormatter())
        else:
            handler.setFormatter(TextFormatter())

        level = getattr(logging, settings.log_level.upper(), logging.INFO)
        self._logger.setLevel(level)
        self._logger.addHandler(handler)
        self._logger.propagate = False

    def _log_event(self, event_type: LogEventType, extra: dict[str, Any]) -> None:
        """Log a structured event at INFO level with extra fields."""
        self._logger.info(
            event_type.value,
            extra={"event": event_type.value, **extra},
        )

    def emit_file_started(self, file_id: str, file_name: str, partner: str) -> None:
        """Log FILE_STARTED event with file context."""
        self._log_event(LogEventType.FILE_STARTED, {
            "file_id": _sanitize(file_id),
            "file_name": _sanitize(file_name),
            "partner": _sanitize(partner),
        })

    def emit_file_completed(
        self,
        file_id: str,
        total: int,
        success: int,
        failed: int,
        duration_ms: float,
    ) -> None:
        """Log FILE_COMPLETED event with processing stats."""
        self._log_event(LogEventType.FILE_COMPLETED, {
            "file_id": _sanitize(file_id),
            "total": total,
            "success": success,
            "failed": failed,
            "duration_ms": duration_ms,
        })

    def emit_file_failed(self, file_id: str, error: str) -> None:
        """Log FILE_FAILED event with error reason."""
        self._log_event(LogEventType.FILE_FAILED, {
            "file_id": _sanitize(file_id),
            "error": _sanitize(error),
        })

    def emit_ingestion_stage(
        self,
        stage: str,
        run_id: str,
        source_file_id: str | None = None,
        error_code: str | None = None,
        *,
        partner: str | None = None,
        source_unit_key: str | None = None,
        page: int | None = None,
        attempt: int = 1,
        checkpoint_before: dict[str, Any] | None = None,
        checkpoint_after: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Log a stage transition with traceable ingestion context."""
        extra: dict[str, Any] = {
            "stage": _sanitize(stage),
            "run_id": _sanitize(run_id),
            "partner": _sanitize(partner),
            "source_file_id": _sanitize(source_file_id),
            "source_unit_key": _sanitize(source_unit_key),
            "page": page,
            "attempt": max(1, int(attempt)),
            "checkpoint_before": _sanitize(checkpoint_before),
            "checkpoint_after": _sanitize(checkpoint_after),
        }
        if error_code is not None:
            extra["error_code"] = _sanitize(error_code)
        if error is not None:
            extra["error"] = _sanitize(error, key="error")
        self._log_event(LogEventType.INGESTION_STAGE, extra)

    def emit_ingestion_observability_write_failed(
        self,
        *,
        run_id: str | None,
        source_file_id: str | None,
        partner: str | None,
        stage: str | None,
        error_code: str = "stage_summary_persist_failed",
    ) -> None:
        """Warn about a telemetry write failure without logging raw failures."""
        try:
            self._logger.warning(
                LogEventType.INGESTION_OBSERVABILITY_WRITE_FAILED.value,
                extra={
                    "event": LogEventType.INGESTION_OBSERVABILITY_WRITE_FAILED.value,
                    "run_id": _sanitize(run_id),
                    "source_file_id": _sanitize(source_file_id),
                    "partner": _sanitize(partner),
                    "stage": _sanitize(stage),
                    "error_code": _sanitize(error_code),
                },
            )
        except Exception:
            # A logging handler must never turn best-effort telemetry into an
            # ingestion failure.
            return

    def emit_row_success(self, file_id: str, row_number: int, trace: str) -> None:
        """Log ROW_SUCCESS event with row context."""
        self._log_event(LogEventType.ROW_SUCCESS, {
            "file_id": _sanitize(file_id),
            "row_number": row_number,
            "trace": _sanitize(trace),
            "status": "SUCCESS",
        })

    def emit_row_failed(
        self, file_id: str, row_number: int, trace: str, reason: str
    ) -> None:
        """Log ROW_FAILED event with error details."""
        self._log_event(LogEventType.ROW_FAILED, {
            "file_id": _sanitize(file_id),
            "row_number": row_number,
            "trace": _sanitize(trace),
            "status": "FAILED",
            "reason": _sanitize(reason),
        })

    def get_logger(self) -> logging.Logger:
        """Return the underlying logging.Logger for direct use."""
        return self._logger


# Module-level singleton
_logger: Optional[StructuredLogger] = None
_lock = threading.Lock()


def get_structured_logger(name: str = "reconciliation") -> StructuredLogger:
    """Get or create the module-level StructuredLogger singleton.

    Uses double-checked locking for thread safety.
    Note: The ``name`` parameter is only used on the first call; subsequent
    calls return the existing singleton regardless of the name provided.
    """
    global _logger
    if _logger is None:
        with _lock:
            if _logger is None:
                _logger = StructuredLogger(name=name)
    return _logger
