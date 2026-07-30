"""IngestionPipeline — orchestrates the full file ingestion flow.

Exports:
    IngestionPipeline: Main pipeline class with async process_file() method.
    IngestionResult: Dataclass holding processing results.
"""

import asyncio
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import string
import time
from typing import Any, Optional

from src.config.config_health import (
    ConfigurationApprovalRequiredError,
    check_and_refresh_config,
    record_config_run_health,
)
from src.config.loader import ConfigLoader
from src.core.enums import ProcessingStatus
from src.core.types import BatchInsertResult, ProcessingStats
from src.logging import StructuredLogger, get_structured_logger
from src.models.data_container import DataContainer, DataContainerRepository, PartnerData
from src.models.mapping_config import MappingConfig, MappingConfigRepository
from src.models.reconciliation_file import ReconciliationFile, ReconciliationFileRepository
from src.normalizer.normalizer import TransactionNormalizer
from src.readers import create_reader
from src.reconciliation.scope import classify_scope
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
        batch_size: int | None = None,
        logger: StructuredLogger | None = None,
        fast_mode: bool = False,
        write_workers: int | None = None,
        ordered_insert: bool | None = None,
    ) -> None:
        """Initialize the ingestion pipeline.

        Args:
            db: AsyncIOMotorDatabase instance.
            config_loader: ConfigLoader for loading mapping configurations.
            batch_size: Number of DataContainer objects to batch before inserting.
            logger: Optional StructuredLogger for lifecycle event emission.
            fast_mode: If True, bypass Pydantic model initialization for faster inserts.
            write_workers: Number of concurrent write workers/tasks.
            ordered_insert: Whether inserts must be ordered.
        """
        from src.config.settings import settings
        self._db = db
        self._config_loader = config_loader
        self._batch_size = batch_size if batch_size is not None else settings.ingest_batch_size
        self._write_workers = write_workers if write_workers is not None else settings.ingest_write_workers
        if self._write_workers < 1:
            raise ValueError("write_workers must be at least 1")
        self._ordered_insert = ordered_insert if ordered_insert is not None else settings.ingest_ordered_insert
        self._recon_repo = ReconciliationFileRepository(db)
        self._data_repo = DataContainerRepository(db)
        self._logger = logger or get_structured_logger()
        self._fast_mode = fast_mode

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

    def _derive_ingestion_key(self, txn: Any) -> str:
        """Derive a stable transaction key from normalized transaction data."""
        if isinstance(txn, dict):
            txn_id = txn.get("id")
            trace = txn.get("trace")
        else:
            txn_id = getattr(txn, "id", None)
            trace = getattr(txn, "trace", None)

        if txn_id:
            return str(txn_id)
        if trace:
            return str(trace)
        raise ValueError("Unable to derive ingestion_key from transaction payload")

    def _derive_fetch_unit_key(
        self,
        *,
        partner: str,
        workflow_type: str,
        file_type: Any,
        reconciliation_date: Any,
        config_version: Optional[str],
        metadata: Optional[dict[str, Any]],
    ) -> Optional[str]:
        if not metadata:
            return None

        identity = {
            "partner": partner,
            "workflowType": workflow_type,
            "fileType": getattr(file_type, "value", file_type),
            "reconciliationDate": reconciliation_date.isoformat(),
            "configVersion": config_version,
            "sourceEndpoint": metadata.get("sourceEndpoint"),
            "page": metadata.get("page"),
            "cursor": metadata.get("cursor"),
            "windowStart": metadata.get("windowStart"),
            "windowEnd": metadata.get("windowEnd"),
        }
        if not identity["sourceEndpoint"]:
            raise ValueError("fetch_unit metadata requires sourceEndpoint")
        if not any(
            identity[field] is not None
            for field in ("page", "cursor", "windowStart", "windowEnd")
        ):
            raise ValueError(
                "fetch_unit metadata requires page, cursor, or a fetch window"
            )

        canonical = json.dumps(
            identity,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    async def _flush_batch(
        self, batch: list[dict]
    ) -> int:
        """Flush a batch of raw dict documents to the database bypassing Pydantic."""
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
        fetch_unit_metadata: Optional[dict[str, Any]] = None,
        enable_config_health_check: bool = False,
    ) -> IngestionResult:
        """Process an entire reconciliation file end-to-end.

        Flow:
        1. Compute SHA256 hash of file_path
        2. Check file duplicate — if found, return early with error
        3. Create ReconciliationFile record with PROCESSING status
        4. (Optional) Config health check — detect stale config + create approval proposal
        5. Load MappingConfig via config_loader
        6. Create stream reader via create_reader
        7. Create TransactionNormalizer with config.field_mappings
        8. Create Validator with data_container_repo and reconciliation_file_repo
        9. For each row: normalize → validate → batch buffer → flush
        10. Flush remaining batch
        11. Update ReconciliationFile stats and status to COMPLETED
        12. Return IngestionResult

        On any exception: update status to FAILED, return partial stats.

        Args:
            file_path: Path to the input file.
            partner: Partner identifier.
            workflow_type: Workflow type string.
            file_type: FileType enum value.
            reconciliation_date: Date of the reconciliation file.
            config_version: Optional config version for load_by_version.
            enable_config_health_check: If True, check config freshness before
                processing and create approval proposals if file structure changed.

        Returns:
            IngestionResult with file_record, stats, and errors.
        """
        # Initialize tracking variables
        total_rows = 0
        success_rows = 0
        failed_rows = 0
        duplicate_rows = 0
        errors: list[dict] = []
        file_record: Optional[ReconciliationFile] = None

        try:
            start_time = time.monotonic()

            # Step 1: Compute file hash
            file_hash = await self._compute_file_hash(file_path)
            fetch_unit_key = self._derive_fetch_unit_key(
                partner=partner,
                workflow_type=workflow_type,
                file_type=file_type,
                reconciliation_date=reconciliation_date,
                config_version=config_version,
                metadata=fetch_unit_metadata,
            )

            # Step 2: Create the canonical file record or resolve a duplicate race.
            file_name = Path(file_path).name
            scope_meta = await classify_scope(
                self._db,
                partner=partner,
                file_name=file_name,
                reconciliation_date=reconciliation_date,
            )
            file_record = ReconciliationFile(
                partner=partner,
                file_name=file_name,
                file_hash=file_hash,
                file_type=file_type,
                reconciliation_date=reconciliation_date,
                processing_status=ProcessingStatus.PROCESSING,
                config_version=config_version,
                fetch_unit_key=fetch_unit_key,
                fetch_unit_metadata=fetch_unit_metadata or {},
                scope_type=scope_meta["scopeType"],
                scope_confidence=scope_meta["scopeConfidence"],
                scope_reason=scope_meta["scopeReason"],
                scope_signals=scope_meta["scopeSignals"],
            )
            existing = await self._recon_repo.find_by_file_hash(file_hash)
            if existing is not None and isinstance(existing, ReconciliationFile):
                file_record = existing
                created = False
            elif hasattr(self._recon_repo, "create_or_get_by_file_hash"):
                res = await self._recon_repo.create_or_get_by_file_hash(file_record)
                if isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], ReconciliationFile):
                    file_record, created = res
                elif isinstance(res, ReconciliationFile):
                    file_record, created = res, True
                else:
                    file_record = await self._recon_repo.create(file_record)
                    created = True
            else:
                file_record = await self._recon_repo.create(file_record)
                created = True

            if not created:
                duplicate_code = (
                    "fetch_unit_duplicate"
                    if fetch_unit_key
                    and file_record.fetch_unit_key == fetch_unit_key
                    and file_record.file_hash != file_hash
                    else "file_duplicate"
                )
                self._logger.emit_file_failed(
                    "duplicate",
                    f"Duplicate ingestion claim ({duplicate_code})",
                )
                stats = ProcessingStats(
                    total_rows=0,
                    success_rows=0,
                    failed_rows=0,
                    duplicate_rows=0,
                )
                return IngestionResult(
                    file_record=file_record,
                    stats=stats,
                    errors=[
                        {
                            "field": duplicate_code,
                            "reason": (
                                "Fetch unit already processed"
                                if duplicate_code == "fetch_unit_duplicate"
                                else f"File already processed (hash: {file_hash[:16]}...)"
                            ),
                        }
                    ],
                )

            # Emit FILE_STARTED event
            self._logger.emit_file_started(str(file_record.id), file_name, partner)

            # Step 4: Load or auto-detect MappingConfig
            config: Optional[MappingConfig] = None

            # 4a: Optional config health check — detect stale + auto-generate
            if enable_config_health_check:
                config_repo = MappingConfigRepository(self._db)
                try:
                    config = await check_and_refresh_config(
                        file_path=file_path,
                        partner=partner,
                        workflow_type=workflow_type,
                        file_type=file_type,
                        config_loader=self._config_loader,
                        config_repo=config_repo,
                        config_version=config_version,
                        source_file_name=file_name,
                        source_file_id=str(file_record.id),
                        source_file_path=file_path,
                        reconciliation_date=reconciliation_date,
                    )
                    self._logger.get_logger().info(
                        f"config_health_check_passed for {partner}"
                    )
                except ConfigurationApprovalRequiredError as approval_exc:
                    approval_reason = (
                        f"configuration approval required for partner={partner}; "
                        f"proposal_id={approval_exc.proposal_id or 'unknown'}; "
                        f"action_id={approval_exc.action_id or 'unknown'}"
                    )
                    await self._recon_repo.update_status(
                        file_record.id, ProcessingStatus.PENDING
                    )
                    file_record.processing_status = ProcessingStatus.PENDING
                    stats = ProcessingStats(
                        total_rows=0,
                        success_rows=0,
                        failed_rows=0,
                    )
                    errors.append({
                        "field": "configApproval",
                        "reason": approval_reason,
                    })
                    return IngestionResult(
                        file_record=file_record,
                        stats=stats,
                        errors=errors,
                    )
                except Exception as hc_exc:
                    self._logger.get_logger().warning(
                        f"Config health check failed for {partner}: {hc_exc} "
                        "- falling back to normal config loading"
                    )

            # 4b: Normal config loading if health check didn't produce one
            if config is None:
                if config_version is not None:
                    config = await self._config_loader.load_by_version(
                        partner, config_version
                    )
                else:
                    config = await self._config_loader.load_by_partner_type(
                        partner, workflow_type, file_type
                    )

            # Step 5-7: Create reader, normalizer, validator
            if config.sheet_name and "{" in config.sheet_name:
                from src.fetchers.base import BaseFetcher
                import copy
                config = copy.copy(config)
                config.sheet_name = BaseFetcher.interpolate_date(config.sheet_name, reconciliation_date)

            t_start_read = time.perf_counter()
            with create_reader(file_path, config) as reader:
                read_file_ms = (time.perf_counter() - t_start_read) * 1000
                normalizer = TransactionNormalizer(config.field_mappings)
                validator = Validator(
                    data_container_repo=self._data_repo,
                    reconciliation_file_repo=self._recon_repo,
                )

                batch_buffer: list[DataContainer] = []
                t_parse = 0.0
                t_normalize = 0.0
                t_validate = 0.0
                t_db_insert = 0.0
                db_write_count = 0
                write_semaphore = asyncio.Semaphore(self._write_workers)
                write_tasks: list[asyncio.Task] = []
                t_db_start_wall = 0.0
                t_db_end_wall = 0.0
                slowest_batch_ms = 0.0

                async def _worker_flush(batch_to_write: list[Any]) -> int:
                    nonlocal t_db_start_wall, t_db_end_wall, slowest_batch_ms
                    t0_loc = time.perf_counter()
                    if t_db_start_wall == 0.0:
                        t_db_start_wall = t0_loc
                    async with write_semaphore:
                        t0_batch = time.perf_counter()
                        res = await self._data_repo.insert_many(
                            batch_to_write,
                            ordered=self._ordered_insert,
                            detailed=True,
                        )
                        batch_duration_ms = (time.perf_counter() - t0_batch) * 1000
                        if batch_duration_ms > slowest_batch_ms:
                            slowest_batch_ms = batch_duration_ms
                    t_db_end_wall = time.perf_counter()
                    return res

                def _record_batch_result(result: int | BatchInsertResult) -> None:
                    nonlocal success_rows, duplicate_rows, failed_rows
                    if isinstance(result, BatchInsertResult):
                        success_rows += result.inserted
                        duplicate_rows += result.duplicates
                        failed_rows += result.failed
                        if result.duplicates:
                            errors.append({
                                "field": "transaction_duplicate",
                                "reason": (
                                    f"{result.duplicates} transaction(s) skipped "
                                    "because the ingestion key already exists"
                                ),
                            })
                        if result.failed:
                            errors.append({
                                "field": "batch_conflict",
                                "reason": (
                                    f"{result.failed} transaction(s) failed "
                                    "during batch persistence"
                                ),
                            })
                    else:
                        success_rows += int(result)

                async def _schedule_flush(batch_to_write: list[Any]) -> None:
                    nonlocal write_tasks
                    if self._write_workers == 1:
                        _record_batch_result(await _worker_flush(batch_to_write))
                        return

                    write_tasks.append(asyncio.create_task(_worker_flush(batch_to_write)))
                    if len(write_tasks) >= self._write_workers:
                        for result in await asyncio.gather(*write_tasks):
                            _record_batch_result(result)
                        write_tasks = []



                # Step 8: Process each row
                row_iterator = reader.iter_rows()
                while True:
                    t0 = time.perf_counter()
                    try:
                        row_tuple = next(row_iterator)
                    except StopIteration:
                        break
                    t_parse += (time.perf_counter() - t0) * 1000

                    total_rows += 1
                    row_number = config.start_row + total_rows - 1

                    # 8b: Normalize
                    t0 = time.perf_counter()
                    norm_result = normalizer.normalize(row_tuple, row_number)

                    # 8c: If normalization errors → failed, collect, continue
                    if norm_result.errors:
                        t_normalize += (time.perf_counter() - t0) * 1000
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

                    # 8d: Build CanonicalTransaction (fast dict or Pydantic)
                    if self._fast_mode:
                        txn, build_errors = TransactionNormalizer.build_fast_dict(
                            norm_result.data, [], row_number
                        )
                    else:
                        txn, build_errors = TransactionNormalizer.build_canonical(
                            norm_result.data, [], row_number
                        )

                    # 8e: If build fails → failed, collect, continue
                    if txn is None:
                        t_normalize += (time.perf_counter() - t0) * 1000
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
                    t_normalize += (time.perf_counter() - t0) * 1000

                    # 8f: Validate (skipped in fast-mode — normalizer already guarantees types)
                    if not self._fast_mode:
                        t0 = time.perf_counter()
                        validation_result = validator.validate(
                            txn,
                            row_number=row_number,
                            trace=txn.trace,
                        )
                        t_validate += (time.perf_counter() - t0) * 1000

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
                    ingestion_key = self._derive_ingestion_key(txn)
                    if self._fast_mode:
                        # Bypass all Pydantic model creation for performance
                        from uuid import uuid4
                        from datetime import datetime, timezone
                        data_container = {
                             "_id": str(uuid4()),
                             "requestId": str(uuid4()),
                             "identify": partner,
                             "workflowType": workflow_type,
                             "reconciliationDate": reconciliation_date,
                             "operationStatus": "IN_PROGRESS",
                             "reconciliationStatus": "",
                             "connectorData": "",
                             "extraData": "",
                             "sourceFileId": str(file_record.id),
                             "ingestion_key": ingestion_key,
                             "partnerData": {
                                 "_id": txn["id"],
                                 "trace": txn["trace"],
                                 "status": txn["status"],
                                 "amount": txn["amount"],
                                 "currency": txn["currency"],
                                 "transDate": txn["transDate"],
                                 "extra": txn["extra"],
                             },
                             "createdBy": "system",
                             "createdDate": datetime.now(timezone.utc),
                             "lastModifiedBy": "system",
                             "lastModifiedDate": datetime.now(timezone.utc)
                        }
                    else:
                        # Standard Pydantic model creation
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
                            ingestion_key=ingestion_key,
                            partner_data=partner_data,
                        )
                    batch_buffer.append(data_container)

                    # 8i: Flush when batch reaches batch_size
                    if len(batch_buffer) >= self._batch_size:
                        await _schedule_flush(batch_buffer)
                        db_write_count += 1
                        batch_buffer = []

                # Step 9: Flush remaining batch
                if batch_buffer:
                    await _schedule_flush(batch_buffer)
                    db_write_count += 1

                # Wait for all writing tasks to finish
                if write_tasks:
                    results = await asyncio.gather(*write_tasks)
                    for result in results:
                        _record_batch_result(result)
                if t_db_start_wall > 0.0:
                    t_db_insert = (t_db_end_wall - t_db_start_wall) * 1000


            # Step 10: Update stats and status
            t_post_start = time.perf_counter()
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

            if enable_config_health_check:
                config_repo = MappingConfigRepository(self._db)
                await record_config_run_health(
                    config_repo=config_repo,
                    partner=partner,
                    workflow_type=workflow_type,
                    file_type=file_type,
                    config_version=config_version,
                    total_rows=total_rows,
                    failed_rows=failed_rows,
                )

            # Emit FILE_COMPLETED event
            duration_ms = (time.monotonic() - start_time) * 1000
            self._logger.emit_file_completed(
                str(file_record.id), total_rows, success_rows, failed_rows, duration_ms,
            )
            post_insert_update_ms = (time.perf_counter() - t_post_start) * 1000

            # Print structured performance log
            perf_log = (
                f"PERF_INGEST: total_ingest_ms={duration_ms:.2f} read_file_ms={read_file_ms:.2f} "
                f"parse_rows_ms={t_parse:.2f} normalize_ms={t_normalize:.2f} validate_ms={t_validate:.2f} "
                f"deduplicate_ms=0.00 db_insert_ms={t_db_insert:.2f} post_insert_update_ms={post_insert_update_ms:.2f} "
                f"records_count={total_rows} batch_size={self._batch_size} "
                f"db_write_operation_count={db_write_count + 2} error_count={len(errors)} slowest_batch_ms={slowest_batch_ms:.2f}"
            )
            print(perf_log, flush=True)
            if hasattr(self._logger, "get_logger"):
                self._logger.get_logger().info(perf_log)
            else:
                import logging
                logging.getLogger("reconciliation").info(perf_log)

            # Step 11: Return result
            stats = ProcessingStats(
                total_rows=total_rows,
                success_rows=success_rows,
                failed_rows=failed_rows,
                duplicate_rows=duplicate_rows,
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
                duplicate_rows=duplicate_rows,
            )
            errors.append({
                "field": "persistence_error",
                "reason": str(exc),
            })
            return IngestionResult(
                file_record=file_record,
                stats=stats,
                errors=errors,
            )
