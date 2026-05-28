"""IngestionPipeline — orchestrates the full file ingestion flow.

Exports:
    IngestionPipeline: Main pipeline class with async process_file() method.
    IngestionResult: Dataclass holding processing results.
"""

import asyncio
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import string
import time
from typing import Any, Optional

from src.config.loader import ConfigLoader
from src.core.enums import ProcessingStatus
from src.core.types import ProcessingStats
from src.logging import StructuredLogger, get_structured_logger
from src.models.data_container import DataContainer, DataContainerRepository, PartnerData
from src.models.mapping_config import MappingConfig
from src.models.reconciliation_file import ReconciliationFile, ReconciliationFileRepository
from src.normalizer.normalizer import TransactionNormalizer
from src.readers import create_reader
from src.validators.validator import Validator


@dataclass
class IngestionResult:
    """Result of a file ingestion run.

    Attributes:
        file_record: The ReconciliationFile tracking record.
        stats: Processing statistics (total/success/failed rows).
        errors: List of error dicts collected during processing.
    """

    file_record: ReconciliationFile
    stats: ProcessingStats
    errors: list[dict] = field(default_factory=list)


class IngestionPipeline:
    """Orchestrates the full ingestion flow: file → config → normalize → validate → persist.

    Single entry point that wires all components together into a cohesive
    processing pipeline with batch insertion, per-row error handling,
    and accurate statistics tracking.
    """

    def __init__(
        self,
        db: Any,
        config_loader: ConfigLoader,
        batch_size: int = 100,
        logger: StructuredLogger | None = None,
    ) -> None:
        """Initialize the ingestion pipeline.

        Args:
            db: AsyncIOMotorDatabase instance.
            config_loader: ConfigLoader for loading mapping configurations.
            batch_size: Number of DataContainer objects to batch before inserting.
            logger: Optional StructuredLogger for lifecycle event emission.
        """
        self._db = db
        self._config_loader = config_loader
        self._batch_size = batch_size
        self._recon_repo = ReconciliationFileRepository(db)
        self._data_repo = DataContainerRepository(db)
        self._logger = logger or get_structured_logger()

    async def _compute_file_hash(self, file_path: str) -> str:
        """Compute SHA256 hash of the file content.

        Runs synchronous file I/O in a thread pool executor to avoid
        blocking the async event loop.

        Args:
            file_path: Path to the file.

        Returns:
            Hex-encoded SHA256 hash string.
        """
        def _hash_sync() -> str:
            sha256 = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha256.update(chunk)
            return sha256.hexdigest()

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _hash_sync)

    def _tuple_to_dict(self, row_tuple: tuple) -> dict[str, Any]:
        """Convert a row tuple to a dict keyed by column letter.

        Index 0 → "A", 1 → "B", etc.

        Args:
            row_tuple: Tuple of cell values from ExcelStreamReader.

        Returns:
            Dict mapping column letters to cell values.
        """
        return {
            string.ascii_uppercase[i]: value
            for i, value in enumerate(row_tuple)
        }

    async def _flush_batch(
        self, batch: list[DataContainer]
    ) -> int:
        """Flush a batch of DataContainer objects to the database.

        Uses collection.insert_many for bulk insertion.

        Args:
            batch: List of DataContainer objects to insert.

        Returns:
            Number of documents inserted.
        """
        if not batch:
            return 0
        count = await self._data_repo.insert_many(batch)
        return count

    async def process_file(
        self,
        file_path: str,
        partner: str,
        workflow_type: str,
        file_type: Any,  # FileType enum
        reconciliation_date: Any,  # datetime
        config_version: Optional[str] = None,
    ) -> IngestionResult:
        """Process an entire reconciliation file end-to-end.

        Flow:
        1. Compute SHA256 hash of file_path
        2. Check file duplicate — if found, return early with error
        3. Create ReconciliationFile record with PROCESSING status
        4. Load MappingConfig via config_loader
        5. Create stream reader via create_reader
        6. Create TransactionNormalizer with config.field_mappings
        7. Create Validator with data_container_repo and reconciliation_file_repo
        8. For each row: normalize → validate → batch buffer → flush
        9. Flush remaining batch
        10. Update ReconciliationFile stats and status to COMPLETED
        11. Return IngestionResult

        On any exception: update status to FAILED, return partial stats.

        Args:
            file_path: Path to the input file.
            partner: Partner identifier.
            workflow_type: Workflow type string.
            file_type: FileType enum value.
            reconciliation_date: Date of the reconciliation file.
            config_version: Optional config version for load_by_version.

        Returns:
            IngestionResult with file_record, stats, and errors.
        """
        # Initialize tracking variables
        total_rows = 0
        success_rows = 0
        failed_rows = 0
        errors: list[dict] = []
        file_record: Optional[ReconciliationFile] = None

        try:
            start_time = time.monotonic()

            # Step 1: Compute file hash
            file_hash = await self._compute_file_hash(file_path)

            # Step 2: Check for duplicate
            existing = await self._recon_repo.find_by_file_hash(file_hash)
            if existing is not None:
                # File already processed — emit FILE_FAILED and return early
                self._logger.emit_file_failed(
                    "duplicate",
                    f"File already processed (hash: {file_hash[:16]}...)",
                )
                stats = ProcessingStats(
                    total_rows=0, success_rows=0, failed_rows=0
                )
                return IngestionResult(
                    file_record=existing,
                    stats=stats,
                    errors=[
                        {
                            "field": "file_duplicate",
                            "reason": f"File already processed (hash: {file_hash[:16]}...)",
                        }
                    ],
                )

            # Step 3: Create ReconciliationFile with PROCESSING status
            file_name = Path(file_path).name
            file_record = ReconciliationFile(
                partner=partner,
                file_name=file_name,
                file_hash=file_hash,
                file_type=file_type,
                reconciliation_date=reconciliation_date,
                processing_status=ProcessingStatus.PROCESSING,
                config_version=config_version,
            )
            file_record = await self._recon_repo.create(file_record)

            # Emit FILE_STARTED event
            self._logger.emit_file_started(str(file_record.id), file_name, partner)

            # Step 4: Load MappingConfig
            if config_version is not None:
                config = await self._config_loader.load_by_version(
                    partner, config_version
                )
            else:
                config = await self._config_loader.load_by_partner_type(
                    partner, workflow_type, file_type
                )

            # Step 5-7: Create reader, normalizer, validator
            with create_reader(file_path, config) as reader:
                normalizer = TransactionNormalizer(config.field_mappings)
                validator = Validator(
                    data_container_repo=self._data_repo,
                    reconciliation_file_repo=self._recon_repo,
                )

                batch_buffer: list[DataContainer] = []

                # Step 8: Process each row
                for row_tuple in reader.iter_rows():
                    total_rows += 1
                    row_number = config.start_row + total_rows - 1

                    # 8b: Normalize (pass row tuple directly — normalizer uses column numbers)
                    norm_result = normalizer.normalize(row_tuple, row_number)

                    # 8c: If normalization errors → failed, collect, continue
                    if norm_result.errors:
                        failed_rows += 1
                        for err in norm_result.errors:
                            errors.append({
                                "row": err.row,
                                "field": err.field,
                                "reason": err.reason,
                            })
                        self._logger.emit_row_failed(
                            str(file_record.id),
                            row_number,
                            f"row:{row_number}",
                            norm_result.errors[0].reason,
                        )
                        continue

                    # 8d: Build CanonicalTransaction
                    txn, build_errors = TransactionNormalizer.build_canonical(
                        norm_result.data, [], row_number
                    )

                    # 8e: If build fails → failed, collect, continue
                    if txn is None:
                        failed_rows += 1
                        for err in build_errors:
                            errors.append({
                                "row": err.row,
                                "field": err.field,
                                "reason": err.reason,
                            })
                        self._logger.emit_row_failed(
                            str(file_record.id),
                            row_number,
                            f"row:{row_number}",
                            build_errors[0].reason,
                        )
                        continue

                    # 8f: Validate (skip file duplicate check — already done at pipeline level)
                    validation_result = validator.validate(
                        txn,
                        row_number=row_number,
                        trace=txn.trace,
                    )

                    # 8h: If invalid → failed, collect, continue
                    if not validation_result.is_valid:
                        failed_rows += 1
                        for err in validation_result.errors:
                            errors.append({
                                "row": err.row,
                                "field": err.field,
                                "reason": err.reason,
                                "trace": err.trace,
                            })
                        self._logger.emit_row_failed(
                            str(file_record.id),
                            row_number,
                            txn.trace or "",
                            validation_result.errors[0].reason,
                        )
                        continue

                    # 8g: Valid → add to batch buffer
                    partner_data = PartnerData(
                        **{"_id": txn.id},
                        trace=txn.trace,
                        status=txn.status.value,
                        amount=txn.amount,
                        currency=txn.currency,
                        transDate=txn.transDate,
                        extra=txn.extra,
                    )
                    data_container = DataContainer(
                        identify=partner,
                        workflow_type=workflow_type,
                        reconciliation_date=reconciliation_date,
                        source_file_id=file_record.id,
                        partner_data=partner_data,
                    )
                    batch_buffer.append(data_container)

                    # Emit ROW_SUCCESS event
                    self._logger.emit_row_success(
                        str(file_record.id),
                        row_number,
                        txn.trace or "",
                    )

                    # 8i: Flush when batch reaches batch_size
                    if len(batch_buffer) >= self._batch_size:
                        inserted = await self._flush_batch(batch_buffer)
                        success_rows += inserted
                        batch_buffer = []

                # Step 9: Flush remaining batch
                if batch_buffer:
                    inserted = await self._flush_batch(batch_buffer)
                    success_rows += inserted

            # Step 10: Update stats and status
            if file_record is not None:
                await self._recon_repo.update_processing_stats(
                    file_record.id, total_rows, success_rows, failed_rows
                )
                await self._recon_repo.update_status(
                    file_record.id, ProcessingStatus.COMPLETED
                )
                file_record.processing_status = ProcessingStatus.COMPLETED
                file_record.total_rows = total_rows
                file_record.success_rows = success_rows
                file_record.failed_rows = failed_rows

            # Emit FILE_COMPLETED event
            duration_ms = (time.monotonic() - start_time) * 1000
            self._logger.emit_file_completed(
                str(file_record.id), total_rows, success_rows, failed_rows, duration_ms,
            )

            # Step 11: Return result
            stats = ProcessingStats(
                total_rows=total_rows,
                success_rows=success_rows,
                failed_rows=failed_rows,
            )
            return IngestionResult(
                file_record=file_record,
                stats=stats,
                errors=errors,
            )

        except Exception as exc:
            # Step: On exception → set status to FAILED
            duration_ms = (time.monotonic() - start_time) * 1000
            self._logger.emit_file_failed(
                str(file_record.id) if file_record else "unknown",
                str(exc),
            )
            if file_record is not None:
                try:
                    await self._recon_repo.update_processing_stats(
                        file_record.id, total_rows, success_rows, failed_rows
                    )
                    await self._recon_repo.update_status(
                        file_record.id, ProcessingStatus.FAILED
                    )
                    file_record.processing_status = ProcessingStatus.FAILED
                    file_record.total_rows = total_rows
                    file_record.success_rows = success_rows
                    file_record.failed_rows = failed_rows
                except Exception:
                    pass  # Best effort — original error is more important

            stats = ProcessingStats(
                total_rows=total_rows,
                success_rows=success_rows,
                failed_rows=failed_rows,
            )
            errors.append({
                "field": "pipeline",
                "reason": str(exc),
            })
            return IngestionResult(
                file_record=file_record,
                stats=stats,
                errors=errors,
            )
