"""Compatibility facade for post-approval replay use cases."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from src.analysis.insights import invalidate_insight_cache
from src.application.review import post_approval_reconciliation as _post
from src.application.review import staged_page_replay as _staged
from src.application.review.post_approval_reconciliation import (
    reconcile_approved_packet as _reconcile_approved_packet,
)
from src.application.review.staged_page_replay import replay_staged_pages as _replay_staged_pages
from src.application.review.raw_stream import resolve_review_source_file
from src.application.runtime.service import create_runtime_run, update_runtime_run
from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository
from src.infrastructure.ingestion.raw_page_repository import RawIngestionPageRepository
from src.infrastructure.ingestion.composition import build_ingestion_pipeline
from src.infrastructure.mapping.composition import build_config_loader
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.infrastructure.partner_transaction.repository import DataContainerRepository
from src.infrastructure.postgres.reconciliation_result_repository import (
    ReconciliationResultRepository,
)
from src.infrastructure.reconciliation.composition import build_reconciliation_service
from src.infrastructure.review.repository import ReviewPacketRepository


ScheduleBackground = Callable[[Awaitable[None]], None]


async def _update_post_approval_run(*args: Any, **kwargs: Any) -> None:
    await _post.update_post_approval_run(*args, **kwargs)


async def _rebind_replacement_transactions(
    *,
    db: Any,
    packet: Any,
    config: Any,
    ingestion_result: Any,
    source_file_id: str,
) -> int:
    return await _post.rebind_replacement_transactions(
        db=db,
        packet=packet,
        config=config,
        ingestion_result=ingestion_result,
        source_file_id=source_file_id,
        transaction_repo_factory=DataContainerRepository,
    )


def _sync_staged_compatibility_points() -> None:
    setattr(_staged, "RawIngestionPageRepository", RawIngestionPageRepository)
    setattr(_staged, "ReconciliationFileRepository", ReconciliationFileRepository)
    setattr(_staged, "DataContainerRepository", DataContainerRepository)
    setattr(_staged, "ReconciliationResultRepository", ReconciliationResultRepository)
    setattr(_staged, "build_ingestion_pipeline", build_ingestion_pipeline)
    setattr(_staged, "build_config_loader", build_config_loader)
    setattr(_staged, "build_reconciliation_service", build_reconciliation_service)
    setattr(_staged, "update_runtime_run", update_runtime_run)
    setattr(_staged, "_update_post_approval_run", _update_post_approval_run)
    setattr(_staged, "_rebind_replacement_transactions", _rebind_replacement_transactions)


async def reprocess_staged_pages(
    *,
    db: Any,
    packet: Any,
    config: Any,
    run_id: str,
    runtime_run_id: str,
    raw_stage_key: str,
) -> dict | None:
    """Compatibility entry point delegating page replay to its application service."""
    _sync_staged_compatibility_points()
    return await _replay_staged_pages(
        db=db,
        packet=packet,
        config=config,
        run_id=run_id,
        runtime_run_id=runtime_run_id,
        raw_stage_key=raw_stage_key,
    )


async def reprocess_and_reconcile(
    db: Any,
    packet: Any,
    config: Any,
    run_id: str,
    *,
    updater: Callable[..., Awaitable[None]] | None = None,
) -> dict | None:
    """Compatibility entry point delegating the post-approval lifecycle."""
    return await _reconcile_approved_packet(
        db,
        packet,
        config,
        run_id,
        updater=updater or _update_post_approval_run,
        staged_replayer=reprocess_staged_pages,
        source_resolver=resolve_review_source_file,
        runtime_creator=create_runtime_run,
        runtime_updater=update_runtime_run,
        file_repository_factory=ReconciliationFileRepository,
        transaction_repository_factory=DataContainerRepository,
        result_repository_factory=ReconciliationResultRepository,
        pipeline_builder=_staged.build_ingestion_pipeline,
        config_loader_builder=build_config_loader,
        reconciliation_service_builder=build_reconciliation_service,
        replacement_rebinder=_rebind_replacement_transactions,
        cache_invalidator=invalidate_insight_cache,
    )


async def _run_post_approval_reprocess(
    db: Any,
    run_id: str,
    packet_id: str,
    config_id: str,
) -> None:
    await _post.run_post_approval_reprocess(
        db,
        run_id,
        packet_id,
        config_id,
        packet_repository_factory=ReviewPacketRepository,
        config_repository_factory=MappingConfigRepository,
        updater=_update_post_approval_run,
        processor=reprocess_and_reconcile,
    )


async def queue_post_approval_reprocess(
    db: Any,
    packet: Any,
    config: Any,
    *,
    schedule_background: ScheduleBackground,
) -> dict[str, Any]:
    return await _post.queue_post_approval_reprocess(
        db,
        packet,
        config,
        schedule_background=schedule_background,
        run_task=_run_post_approval_reprocess,
    )


async def reprocess_file(db: Any, packet: Any, config: Any, run_id: str) -> dict | None:
    """Replay a file-level review packet and reconcile its transactions."""
    return await reprocess_and_reconcile(db, packet, config, run_id)


async def start_post_approval_reprocess(
    db: Any,
    packet: Any,
    config: Any,
    *,
    schedule_background: ScheduleBackground,
) -> dict[str, Any]:
    """Create and schedule a durable post-approval operation."""
    return await queue_post_approval_reprocess(
        db,
        packet,
        config,
        schedule_background=schedule_background,
    )


serialize_post_approval_run = _post.serialize_post_approval_run
