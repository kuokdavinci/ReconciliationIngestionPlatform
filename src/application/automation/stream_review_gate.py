"""Review-gate orchestration for completed source streams."""

from typing import Any

from src.config.config_health import (
    check_and_refresh_config,
    create_stream_scope_review_packet,
)


async def evaluate_stream_mapping(**kwargs: Any):
    """Evaluate mapping health before a staged stream enters ingestion."""
    return await check_and_refresh_config(**kwargs)


async def create_stream_review_packet(**kwargs: Any):
    """Create the review item for a stream with an active mapping."""
    return await create_stream_scope_review_packet(**kwargs)
