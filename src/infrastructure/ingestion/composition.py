"""Composition root for the ingestion pipeline."""

from typing import Any

from src.config.cache import ConfigCache
from src.config.loader import ConfigLoader
from src.config.validator import ConfigValidator
from src.core.enums import FileType
from src.pipeline.ingestion_pipeline import IngestionPipeline


def build_ingestion_pipeline(
    db: Any,
    *,
    config_loader: ConfigLoader | None = None,
    batch_size: int | None = None,
    logger: Any = None,
    fast_mode: bool = False,
    write_workers: int | None = None,
    ordered_insert: bool | None = None,
    file_repo: Any | None = None,
    partner_repo: Any | None = None,
    mapping_repo: Any | None = None,
    quarantine_repo: Any | None = None,
) -> IngestionPipeline:
    """Build ingestion with production persistence adapters.

    Optional repositories are injectable for unit tests and future adapter
    migrations. Existing callers may still provide a custom ConfigLoader.
    """

    from src.infrastructure.partner_transaction.repository import DataContainerRepository
    from src.infrastructure.mapping.config_repository import MappingConfigRepository
    from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository
    from src.infrastructure.ingestion.quarantine_repository import IngestionQuarantineRepository

    if mapping_repo is None:
        mapping_repo = MappingConfigRepository(db)
    if config_loader is None:
        config_loader = ConfigLoader(mapping_repo, ConfigCache(), ConfigValidator())

    if file_repo is None:
        file_repo = ReconciliationFileRepository(db)
    if partner_repo is None:
        partner_repo = DataContainerRepository(db)
    if quarantine_repo is None:
        quarantine_repo = IngestionQuarantineRepository(db)

    return IngestionPipeline(
        db=db,
        config_loader=config_loader,
        batch_size=batch_size,
        logger=logger,
        fast_mode=fast_mode,
        write_workers=write_workers,
        ordered_insert=ordered_insert,
        file_repo=file_repo,
        partner_repo=partner_repo,
        mapping_repo=mapping_repo,
        quarantine_repo=quarantine_repo,
    )


def build_quarantine_resolution_service(
    db: Any,
    *,
    quarantine_repo: Any | None = None,
    source_file_repo: Any | None = None,
    raw_page_repo: Any | None = None,
    row_processor: Any | None = None,
    persist_row: Any | None = None,
    transaction_repo: Any | None = None,
    existing_fingerprint_reader: Any | None = None,
    audit_recorder: Any | None = None,
    config_loader: ConfigLoader | None = None,
    workflow_type: str = "UPC",
    file_type: FileType = FileType.SETTLEMENT,
    fast_mode: bool = True,
) -> Any:
    """Assemble quarantine resolution around the shared row/persistence ports.

    The row processor is injected by the caller's mapping context so
    quarantine reprocessing cannot silently create a second normalizer or
    validation implementation.
    """
    from src.application.ingestion.quarantine_service import QuarantineResolutionService
    from src.application.audit.service import record_audit_event
    from src.infrastructure.ingestion.file_repository import ReconciliationFileRepository
    from src.infrastructure.mapping.composition import build_config_loader
    from src.infrastructure.ingestion.quarantine_repository import IngestionQuarantineRepository
    from src.infrastructure.ingestion.raw_page_repository import RawIngestionPageRepository
    from src.infrastructure.partner_transaction.repository import DataContainerRepository

    quarantine_repo = quarantine_repo or IngestionQuarantineRepository(db)
    source_file_repo = source_file_repo or ReconciliationFileRepository(db)
    raw_page_repo = raw_page_repo or RawIngestionPageRepository(db)
    transaction_repo = transaction_repo or DataContainerRepository(db)
    row_processor_factory = None
    if row_processor is None:
        config_loader = config_loader or build_config_loader(db)

        async def row_processor_factory(record: Any, request: Any) -> Any:
            selected_version = request.mapping_version or record.config_version
            if selected_version:
                config = await config_loader.load_by_version(record.partner, selected_version)
            else:
                config = await config_loader.load_by_partner_type(
                    record.partner,
                    workflow_type,
                    file_type,
                )

            from src.normalizer.normalizer import TransactionNormalizer
            from src.pipeline.row_processor import RowProcessor
            from src.validators.validator import Validator

            return RowProcessor(
                normalizer=TransactionNormalizer(
                    config.field_mappings,
                    timestamp_policy=config.timestamp_policy,
                ),
                validator=Validator(),
                fast_mode=fast_mode,
                partner=record.partner,
                workflow_type=config.workflow_type,
                reconciliation_date=record.reconciliation_date,
                source_file_id=record.source_file_id,
            )
    if audit_recorder is None:
        async def audit_recorder(**kwargs: Any) -> Any:
            return await record_audit_event(db, **kwargs)

    return QuarantineResolutionService(
        quarantine_repo,
        source_file_repo,
        raw_page_repo,
        row_processor=row_processor,
        row_processor_factory=row_processor_factory,
        persist_row=persist_row,
        transaction_repo=transaction_repo,
        existing_fingerprint_reader=existing_fingerprint_reader,
        audit_recorder=audit_recorder,
    )
