"""Unit tests for structured logger — RED phase (failing tests)."""

import json
import logging
from io import StringIO


from src.logging.logger import (
    JSONFormatter,
    LogEventType,
    StructuredLogger,
    TextFormatter,
    get_structured_logger,
)


class TestLogEventType:
    """Test LogEventType enum values."""

    def test_file_started_exists(self):
        assert LogEventType.FILE_STARTED == "FILE_STARTED"

    def test_file_completed_exists(self):
        assert LogEventType.FILE_COMPLETED == "FILE_COMPLETED"

    def test_file_failed_exists(self):
        assert LogEventType.FILE_FAILED == "FILE_FAILED"

    def test_row_success_exists(self):
        assert LogEventType.ROW_SUCCESS == "ROW_SUCCESS"

    def test_row_failed_exists(self):
        assert LogEventType.ROW_FAILED == "ROW_FAILED"


class TestJSONFormatter:
    """Test JSON formatter output."""

    def test_output_is_valid_json(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test message", args=(), exc_info=None,
        )
        record.event = "TEST_EVENT"
        output = formatter.format(record)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_output_contains_timestamp(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test message", args=(), exc_info=None,
        )
        record.event = "TEST_EVENT"
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "timestamp" in parsed

    def test_output_contains_level(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test message", args=(), exc_info=None,
        )
        record.event = "TEST_EVENT"
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "level" in parsed

    def test_output_contains_event(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test message", args=(), exc_info=None,
        )
        record.event = "TEST_EVENT"
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "event" in parsed
        assert parsed["event"] == "TEST_EVENT"

    def test_output_contains_extra_fields(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test message", args=(), exc_info=None,
        )
        record.event = "TEST_EVENT"
        record.file_id = "file-123"
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed.get("file_id") == "file-123"


class TestTextFormatter:
    """Test text formatter output."""

    def test_output_contains_level_prefix(self):
        formatter = TextFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test message", args=(), exc_info=None,
        )
        record.event = "TEST_EVENT"
        output = formatter.format(record)
        assert "[INFO]" in output

    def test_output_contains_event_name(self):
        formatter = TextFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test message", args=(), exc_info=None,
        )
        record.event = "TEST_EVENT"
        output = formatter.format(record)
        assert "TEST_EVENT" in output


class TestStructuredLogger:
    """Test StructuredLogger emit methods."""

    def _capture_json_output(self, logger: StructuredLogger):
        """Replace handler stream with StringIO and return (stream, old_handler)."""
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JSONFormatter())
        old_handlers = logger._logger.handlers[:]
        logger._logger.handlers = [handler]
        return stream, old_handlers

    def _capture_text_output(self, logger: StructuredLogger):
        """Replace handler stream with StringIO for text mode."""
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(TextFormatter())
        old_handlers = logger._logger.handlers[:]
        logger._logger.handlers = [handler]
        return stream, old_handlers

    def test_emit_file_started_json(self):
        logger = StructuredLogger(name="test_started")
        logger._logger.setLevel(logging.DEBUG)
        stream, _ = self._capture_json_output(logger)
        logger.emit_file_started("file-001", "report.xlsx", "PARTNER_A")
        output = stream.getvalue().strip()
        parsed = json.loads(output)
        assert parsed["event"] == "FILE_STARTED"
        assert parsed["file_id"] == "file-001"
        assert parsed["file_name"] == "report.xlsx"
        assert parsed["partner"] == "PARTNER_A"

    def test_emit_file_completed_json(self):
        logger = StructuredLogger(name="test_completed")
        logger._logger.setLevel(logging.DEBUG)
        stream, _ = self._capture_json_output(logger)
        logger.emit_file_completed("file-001", 100, 95, 5, 1234.5)
        output = stream.getvalue().strip()
        parsed = json.loads(output)
        assert parsed["event"] == "FILE_COMPLETED"
        assert parsed["file_id"] == "file-001"
        assert parsed["total"] == 100
        assert parsed["success"] == 95
        assert parsed["failed"] == 5
        assert parsed["duration_ms"] == 1234.5

    def test_emit_file_failed_json(self):
        logger = StructuredLogger(name="test_failed")
        logger._logger.setLevel(logging.DEBUG)
        stream, _ = self._capture_json_output(logger)
        logger.emit_file_failed("file-001", "File not found")
        output = stream.getvalue().strip()
        parsed = json.loads(output)
        assert parsed["event"] == "FILE_FAILED"
        assert parsed["file_id"] == "file-001"
        assert parsed["error"] == "File not found"

    def test_emit_row_success_json(self):
        logger = StructuredLogger(name="test_row_success")
        logger._logger.setLevel(logging.DEBUG)
        stream, _ = self._capture_json_output(logger)
        logger.emit_row_success("file-001", 42, "TRACE001")
        output = stream.getvalue().strip()
        parsed = json.loads(output)
        assert parsed["event"] == "ROW_SUCCESS"
        assert parsed["file_id"] == "file-001"
        assert parsed["row_number"] == 42
        assert parsed["trace"] == "TRACE001"
        assert parsed["status"] == "SUCCESS"

    def test_emit_row_failed_json(self):
        logger = StructuredLogger(name="test_row_failed")
        logger._logger.setLevel(logging.DEBUG)
        stream, _ = self._capture_json_output(logger)
        logger.emit_row_failed("file-001", 42, "TRACE001", "Invalid amount")
        output = stream.getvalue().strip()
        parsed = json.loads(output)
        assert parsed["event"] == "ROW_FAILED"
        assert parsed["file_id"] == "file-001"
        assert parsed["row_number"] == 42
        assert parsed["trace"] == "TRACE001"
        assert parsed["status"] == "FAILED"
        assert parsed["reason"] == "Invalid amount"

    def test_emit_file_started_text(self):
        logger = StructuredLogger(name="test_started_text")
        logger._logger.setLevel(logging.DEBUG)
        stream, _ = self._capture_text_output(logger)
        logger.emit_file_started("file-001", "report.xlsx", "PARTNER_A")
        output = stream.getvalue()
        assert "[INFO]" in output
        assert "FILE_STARTED" in output
        assert "file-001" in output

    def test_get_logger_returns_underlying_logger(self):
        logger = StructuredLogger(name="test_get_logger")
        underlying = logger.get_logger()
        assert isinstance(underlying, logging.Logger)

    def test_singleton_behavior(self):
        logger1 = get_structured_logger()
        logger2 = get_structured_logger()
        assert logger1 is logger2


class TestLogLevelFiltering:
    """Test log level filtering."""

    def test_debug_suppressed_at_info_level(self):
        logger = StructuredLogger(name="test_level_filter")
        logger._logger.setLevel(logging.INFO)
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JSONFormatter())
        logger._logger.handlers = [handler]
        # Emit at DEBUG level — should not appear
        logger._logger.debug("debug message", extra={"event": "DEBUG_EVENT"})
        output = stream.getvalue().strip()
        assert output == ""

    def test_info_emitted_at_info_level(self):
        logger = StructuredLogger(name="test_level_info")
        logger._logger.setLevel(logging.INFO)
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JSONFormatter())
        logger._logger.handlers = [handler]
        logger._logger.info("info message", extra={"event": "INFO_EVENT"})
        output = stream.getvalue().strip()
        parsed = json.loads(output)
        assert parsed["event"] == "INFO_EVENT"
