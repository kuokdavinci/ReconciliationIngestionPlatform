"""Public application boundary for post-approval replay and reconciliation."""

from typing import Any

from src.application.review.actions import (
    _queue_post_approval_reprocess,
    _reprocess_staged_pages,
    reprocess_and_reconcile,
)


async def reprocess_file(db: Any, packet, config, run_id: str) -> dict | None:
    """Replay a file-level review packet and reconcile its transactions."""

    return await reprocess_and_reconcile(db, packet, config, run_id)


async def reprocess_staged_pages(
    *,
    db: Any,
    packet,
    config,
    run_id: str,
    runtime_run_id: str,
    raw_stage_key: str,
) -> dict | None:
    """Replay retained API pages as one logical reconciliation file."""

    return await _reprocess_staged_pages(
        db=db,
        packet=packet,
        config=config,
        run_id=run_id,
        runtime_run_id=runtime_run_id,
        raw_stage_key=raw_stage_key,
    )


async def start_post_approval_reprocess(
    db: Any,
    packet,
    config,
    *,
    schedule_background,
) -> dict:
    """Create and schedule a durable post-approval operation."""

    return await _queue_post_approval_reprocess(
        db,
        packet,
        config,
        schedule_background=schedule_background,
    )
