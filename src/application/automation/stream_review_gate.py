"""Review-gate orchestration for completed source streams.

Re-exports from stream_runtime.py for backwards compatibility.
"""

from src.application.automation.stream_runtime import (
    create_stream_review_packet,
    evaluate_stream_mapping,
)

__all__ = ["evaluate_stream_mapping", "create_stream_review_packet"]
