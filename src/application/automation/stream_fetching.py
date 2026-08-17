"""Source-unit normalization and checkpoint projection for stream runs.

Re-exports from stream_runtime.py for backwards compatibility.
"""

from src.application.automation.stream_runtime import (
    checkpoint_result,
    source_units,
    unit_high_water_mark,
)

__all__ = ["checkpoint_result", "source_units", "unit_high_water_mark"]
