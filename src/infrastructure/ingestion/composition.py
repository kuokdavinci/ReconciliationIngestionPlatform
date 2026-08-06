"""Composition root for the ingestion pipeline."""

from typing import Any

from src.config.cache import ConfigCache
from src.config.loader import ConfigLoader
from src.config.validator import ConfigValidator
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
