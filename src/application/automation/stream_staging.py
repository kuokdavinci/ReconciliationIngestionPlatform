"""Durable raw-page staging boundary for source streams.

Re-exports from stream_runtime.py for backwards compatibility.
"""

from src.application.automation.stream_runtime import stage_stream_unit

__all__ = ["stage_stream_unit"]
