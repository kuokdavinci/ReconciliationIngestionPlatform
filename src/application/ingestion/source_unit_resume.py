"""Production entry point for resuming a source unit after quarantine review."""

from typing import Any

from src.application.automation.stream_ingestion import build_source_unit_ingestor, cleanup_source_unit
from src.application.ingestion.source_unit_orchestrator import resume_held_source_unit
from src.config.settings import settings
from src.core.enums import ProcessingStatus
from src.domain.ingestion.checkpoints import IngestionMode, IngestionCheckpoint
from src.domain.ingestion.quarantine import QuarantineQuery
from src.domain.ingestion.source_units import SourceUnitMetadata
from src.infrastructure.fetch_config.repository import FetchConfigRepository
from src.infrastructure.ingestion.checkpoint_repository import IngestionCheckpointRepository
from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository
from src.infrastructure.ingestion.quarantine_repository import IngestionQuarantineRepository
from src.infrastructure.ingestion.raw_page_repository import RawIngestionPageRepository
from src.infrastructure.mapping.composition import build_config_loader
from src.infrastructure.reconciliation.composition import build_reconciliation_service


def _status_value(value: Any) -> str:
    return str(getattr(value, "value", value))


async def _mapping_version(
    quarantine_repo: Any,
    source_file: Any | None,
    source_unit_key: str,
) -> str | None:
    source_version = getattr(source_file, "config_version", None)
    if source_version:
        return str(source_version)

    finder = getattr(quarantine_repo, "find_many", None)
    if not callable(finder):
        return None
    result = await finder(QuarantineQuery(sourceUnitKey=source_unit_key, limit=200))
    records = result[0] if isinstance(result, tuple) else result
    for record in records or []:
        version = getattr(record, "config_version", None)
        if version:
            return str(version)
    return None


def _unit_from_raw_page(page: Any, checkpoint: IngestionCheckpoint) -> SourceUnitMetadata:
    return SourceUnitMetadata(
        sourceUnitKey=page.source_unit_key,
        localPath=page.local_path,
        page=page.page,
        cursorBefore=page.cursor_before,
        cursorAfter=page.cursor_after,
        contentHash=page.content_hash,
        contentType=page.content_type,
        itemCount=page.item_count,
        hasMore=page.has_more,
        fetchMetadata={
            "rawStageKey": page.stage_key,
            "sampleRows": list(page.sample_rows or []),
            "sourceEndpoint": checkpoint.source_endpoint,
        },
    )


def _unit_from_source_file(source_file: Any) -> SourceUnitMetadata:
    metadata = dict(getattr(source_file, "fetch_unit_metadata", None) or {})
    source_path = getattr(source_file, "source_file_path", None) or metadata.get("localPath")
    return SourceUnitMetadata(
        sourceUnitKey=source_file.fetch_unit_key,
        localPath=source_path,
        fetchMetadata=metadata,
    )


async def resume_quarantined_source_unit(
    db: Any,
    source_unit_key: str,
    *,
    operator_id: str,
    reason: str,
    mode: IngestionMode | None = None,
    batch_size: int | None = None,
    action_id: str | None = None,
    audit_recorder: Any | None = None,
) -> dict[str, Any]:
    """Resume one held unit after all conflicting quarantine records are terminal.

    The unit is reconstructed from durable raw-page or source-file metadata.
    The existing checkpoint state machine remains the only component allowed
    to claim, complete, and advance the unit.
    """
    if not source_unit_key.strip():
        raise ValueError("source_unit_key must not be empty")

    checkpoint_repo = IngestionCheckpointRepository(db)
    quarantine_repo = IngestionQuarantineRepository(db)
    raw_page_repo = RawIngestionPageRepository(db)
    source_file_repo = ReconciliationFileRepository(db)
    page = await raw_page_repo.find_one({"sourceUnitKey": source_unit_key})
    checkpoint = await checkpoint_repo.find_by_source_unit_key(source_unit_key)
    if checkpoint is None and page is not None:
        checkpoint = await checkpoint_repo.find_by_stream(
            partner=page.partner,
            fetch_config_id=page.fetch_config_id,
            source_type=page.source_type,
            stream_key=page.stream_key,
            mode=mode or IngestionMode.SCHEDULED,
        )
    if checkpoint is None:
        raise LookupError(f"No checkpoint owns source unit '{source_unit_key}'.")
    if mode is not None and checkpoint.mode is not mode:
        raise ValueError("Requested ingestion mode does not match the source-unit checkpoint.")

    source_file = await source_file_repo.find_by_fetch_unit_key(source_unit_key)
    if page is not None:
        unit = _unit_from_raw_page(page, checkpoint)
        reconciliation_date = page.reconciliation_date
    elif source_file is not None:
        unit = _unit_from_source_file(source_file)
        reconciliation_date = source_file.reconciliation_date
    else:
        raise LookupError(f"No durable source payload owns source unit '{source_unit_key}'.")

    fetch_config = await FetchConfigRepository(db).find_by_id(checkpoint.fetch_config_id)
    if fetch_config is None:
        raise LookupError(
            f"Fetch configuration '{checkpoint.fetch_config_id}' was not found."
        )

    mapping_version = await _mapping_version(
        quarantine_repo,
        source_file,
        source_unit_key,
    )
    ingest_unit, _stats = build_source_unit_ingestor(
        config=fetch_config,
        db=db,
        config_loader=build_config_loader(db),
        partner=checkpoint.partner,
        reconciliation_date=reconciliation_date,
        batch_size=batch_size or settings.ingest_batch_size,
        structured_logger=None,
        mapping_config_version=mapping_version,
        config_health_check_enabled=False,
    )

    async def resume_ingest(resume_unit: SourceUnitMetadata) -> Any:
        # A quarantine hold is emitted after the original file write has
        # completed. Reconcile that committed file instead of replaying its
        # conflicting row and immediately creating the same hold again.
        if source_file is not None and _status_value(
            getattr(source_file, "processing_status", None)
        ) == ProcessingStatus.COMPLETED.value:
            reconciliation_results = await build_reconciliation_service(db).reconcile(
                checkpoint.partner,
                reconciliation_date,
                source_file_id=str(source_file.id),
            )
            return {
                "success": True,
                "outcome": "INGESTED",
                "reconciliationCount": len(reconciliation_results),
            }
        return await ingest_unit(resume_unit)

    async def consume_after_checkpoint(resume_unit: SourceUnitMetadata) -> None:
        if page is not None:
            await raw_page_repo.mark_consumed(resume_unit.source_unit_key or "")
        await cleanup_source_unit(fetch_config, resume_unit)

    result = await resume_held_source_unit(
        checkpoint_repo,
        quarantine_repo,
        source_unit_key=source_unit_key,
        stream_identity={
            "partner": checkpoint.partner,
            "fetchConfigId": checkpoint.fetch_config_id,
            "sourceType": checkpoint.source_type,
            "streamKey": checkpoint.stream_key,
            "configVersion": checkpoint.config_version,
            "sourceEndpoint": checkpoint.source_endpoint,
        },
        unit=unit,
        ingest_unit=resume_ingest,
        mode=checkpoint.mode,
        on_unit_completed=consume_after_checkpoint,
    )
    if result.get("success") and audit_recorder is not None and action_id:
        await audit_recorder(
            entity_type="INGESTION_QUARANTINE_SOURCE_UNIT",
            entity_id=source_unit_key,
            action="QUARANTINE_SOURCE_UNIT_RESUMED",
            actor=operator_id,
            metadata={
                "actionId": action_id.strip()[:128],
                "previousStatus": "HELD",
                "newStatus": "RESUMED",
                "outcome": result.get("outcome", "RESUMED"),
                "reason": reason.strip()[:500],
                "partner": checkpoint.partner,
                "sourceUnitKey": source_unit_key,
            },
        )
    return result


__all__ = ["resume_quarantined_source_unit"]
