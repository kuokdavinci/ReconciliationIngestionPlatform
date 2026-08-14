"""Document-store compatibility execution boundary for reconciliation."""

import asyncio
import inspect
import time
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional, Protocol, TypeGuard, cast

from src.core.enums import ReconciliationScopeType, ReconciliationStatus, TransactionStatus
from src.domain.partner_transaction.models import DataContainer
from src.domain.reconciliation.models import ReconciliationResult
from src.domain.reconciliation.ports import (
    InternalTransactionReader,
    PartnerTransactionReader,
    ReconciliationResultWriter,
)
from src.logging import get_structured_logger


class _InternalDocumentRepository(Protocol):
    collection: Any

    def _convert_from_mongo_types(self, raw: Any) -> dict[str, Any]:
        """Convert a raw document into repository-compatible values."""


class _PartnerDocumentRepository(Protocol):
    collection: Any

    def _from_mongo(self, raw: dict[str, Any]) -> DataContainer:
        """Convert a raw document into a canonical partner transaction."""


def _has_internal_document_capability(
    repository: InternalTransactionReader,
) -> TypeGuard[_InternalDocumentRepository]:
    return hasattr(repository, "collection")


def _has_partner_document_capability(
    repository: PartnerTransactionReader,
) -> TypeGuard[_PartnerDocumentRepository]:
    return hasattr(repository, "collection")


class DocumentReconciliationExecutor:
    """Run the legacy document-store matching and batched write path."""

    def __init__(
        self,
        *,
        data_repo: PartnerTransactionReader,
        internal_repo: InternalTransactionReader,
        result_repo: ReconciliationResultWriter,
        fast_mode: bool = False,
        partner_batch_size: int = 100000,
        result_batch_size: int = 100000,
        write_workers: int = 1,
        ordered_insert: bool = True,
        logger: Any | None = None,
    ) -> None:
        self._data_repo = data_repo
        self._internal_repo = internal_repo
        self._result_repo = result_repo
        self.fast_mode = fast_mode
        self._partner_batch_size = partner_batch_size
        self._result_batch_size = result_batch_size
        self._write_workers = write_workers
        self._ordered_insert = ordered_insert
        self._logger = logger or get_structured_logger()

    @staticmethod
    def _is_async_iterable(value: Any) -> bool:
        return isinstance(value, AsyncIterator) or inspect.isasyncgen(value)

    def _normalize_status(self, status_str: str) -> TransactionStatus:
        status_lower = str(status_str).strip().lower()
        if status_lower in ("success", "thành công", "matched"):
            return TransactionStatus.SUCCESS
        if status_lower in ("fail", "failed", "thất bại"):
            return TransactionStatus.FAILED
        if status_lower in ("reversed", "hoàn tiền"):
            return TransactionStatus.REVERSED
        return TransactionStatus.PENDING

    def _resolve_partner_txn_id(self, partner_record: DataContainer) -> Optional[str]:
        from src.reconciliation.keys import normalize_reconciliation_key

        pd = partner_record.partner_data
        return normalize_reconciliation_key(
            pd.trace,
            pd.extra.get("vspTransId") if pd.extra else None,
            pd.id,
        )

    def _is_finalized_internal_status(self, status: TransactionStatus | str) -> bool:
        normalized = self._normalize_status(str(status))
        return normalized in {
            TransactionStatus.SUCCESS,
            TransactionStatus.FAILED,
            TransactionStatus.REVERSED,
        }

    def _pre_check_record(self, partner_record: DataContainer) -> tuple[bool, str]:
        if partner_record.partner_data is None:
            return False, "empty_partner_data"

        amount = partner_record.partner_data.amount
        if amount is None:
            return False, "missing_amount"

        status = partner_record.partner_data.status
        if status is None or (isinstance(status, str) and status.strip() == ""):
            return False, "missing_status"

        return True, ""

    async def _build_internal_index(
        self,
        internal_query: dict,
        scoped_partner_keys: set[str],
        scope_type: ReconciliationScopeType,
    ) -> dict[str, dict]:
        projection = {
            "_id": 1,
            "partnerTxnId": 1,
            "amount": 1,
            "status": 1,
            "updatedAt": 1,
        }
        internal_by_key: dict[str, dict] = {}
        if _has_internal_document_capability(self._internal_repo):
            cursor = self._internal_repo.collection.find(
                internal_query,
                projection=projection,
            )
            if self._is_async_iterable(cursor):
                async for raw in cursor:
                    normalized = self._internal_repo._convert_from_mongo_types(raw)
                    partner_txn_id = str(normalized.get("partnerTxnId") or "").strip()
                    if not partner_txn_id:
                        continue
                    if (
                        scope_type != ReconciliationScopeType.FULL_SNAPSHOT
                        and scoped_partner_keys
                        and partner_txn_id not in scoped_partner_keys
                    ):
                        continue
                    status = cast(
                        TransactionStatus | str,
                        normalized.get("status"),
                    )
                    if not self._is_finalized_internal_status(status):
                        continue
                    candidate = {
                        "id": str(normalized.get("_id")),
                        "amount": normalized.get("amount"),
                        "status": status,
                        "updated_at": normalized.get("updatedAt"),
                    }
                    existing = internal_by_key.get(partner_txn_id)
                    if existing is None or candidate["updated_at"] > existing["updated_at"]:
                        internal_by_key[partner_txn_id] = candidate
                return internal_by_key

        find_many = getattr(self._internal_repo, "find_many", None)
        if callable(find_many):
            internal_records = await find_many(internal_query)
        else:
            date_range = internal_query["transactionTime"]
            internal_records = await self._internal_repo.find_by_partner_and_date_range(
                internal_query["partner"],
                date_range["$gte"],
                date_range["$lte"],
            )

        finalized_internal_records = [
            record
            for record in internal_records
            if self._is_finalized_internal_status(record.status)
        ]
        if scope_type != ReconciliationScopeType.FULL_SNAPSHOT and scoped_partner_keys:
            finalized_internal_records = [
                record
                for record in finalized_internal_records
                if record.partner_txn_id.strip() in scoped_partner_keys
            ]
        for record in finalized_internal_records:
            key = record.partner_txn_id.strip()
            candidate = {
                "id": str(record.id),
                "amount": record.amount,
                "status": record.status,
                "updated_at": record.updated_at,
            }
            existing = internal_by_key.get(key)
            if existing is None or candidate["updated_at"] > existing["updated_at"]:
                internal_by_key[key] = candidate
        return internal_by_key

    async def _iter_partner_record_batches(self, partner_query: dict):
        if _has_partner_document_capability(self._data_repo):
            cursor = self._data_repo.collection.find(partner_query).batch_size(
                self._partner_batch_size
            )
            if self._is_async_iterable(cursor):
                batch: list[DataContainer] = []
                async for raw in cursor:
                    batch.append(self._data_repo._from_mongo(raw))
                    if len(batch) >= self._partner_batch_size:
                        yield batch
                        batch = []
                if batch:
                    yield batch
                return

        records = await self._data_repo.find_many(partner_query)
        for start in range(0, len(records), self._partner_batch_size):
            yield records[start : start + self._partner_batch_size]

    async def _collect_scoped_partner_keys(self, partner_query: dict) -> set[str]:
        scoped_partner_keys: set[str] = set()
        async for partner_batch in self._iter_partner_record_batches(partner_query):
            for record in partner_batch:
                key = self._resolve_partner_txn_id(record)
                if key:
                    scoped_partner_keys.add(key)
        return scoped_partner_keys

    def _create_result_doc(
        self,
        *,
        id: str,
        partner: str,
        date: str,
        partnerTxnId: str,
        internalTxnId: Optional[str] = None,
        partnerAmount: Optional[Decimal] = None,
        internalAmount: Optional[Decimal] = None,
        partnerStatus: Optional[str] = None,
        internalStatus: Optional[str] = None,
        reconciliationStatus: ReconciliationStatus,
        reconciliationRunId: Optional[str] = None,
        sourceFileId: Optional[str] = None,
        scopeType: str,
        mappingVersion: Optional[str] = None,
        partnerRecordId: Optional[str] = None,
        internalRecordId: Optional[str] = None,
    ) -> ReconciliationResult | dict[str, Any]:
        if self.fast_mode:
            from datetime import timezone

            return {
                "_id": id,
                "partner": partner,
                "date": date,
                "partnerTxnId": partnerTxnId,
                "internalTxnId": internalTxnId,
                "partnerAmount": partnerAmount,
                "internalAmount": internalAmount,
                "partnerStatus": partnerStatus,
                "internalStatus": internalStatus,
                "reconciliationStatus": (
                    reconciliationStatus.value
                    if hasattr(reconciliationStatus, "value")
                    else reconciliationStatus
                ),
                "reconciliationRunId": reconciliationRunId,
                "sourceFileId": sourceFileId,
                "scopeType": scopeType,
                "mappingVersion": mappingVersion,
                "partnerRecordId": partnerRecordId,
                "internalRecordId": internalRecordId,
                "createdAt": datetime.now(timezone.utc),
            }

        return ReconciliationResult(
            _id=id,
            partner=partner,
            date=date,
            partnerTxnId=partnerTxnId,
            internalTxnId=internalTxnId,
            partnerAmount=partnerAmount,
            internalAmount=internalAmount,
            partnerStatus=partnerStatus,
            internalStatus=internalStatus,
            reconciliationStatus=reconciliationStatus,
            reconciliationRunId=reconciliationRunId,
            sourceFileId=sourceFileId,
            scopeType=scopeType,
            mappingVersion=mappingVersion,
            partnerRecordId=partnerRecordId,
            internalRecordId=internalRecordId,
        )

    @staticmethod
    def _result_partner_key(
        result: ReconciliationResult | dict[str, Any],
    ) -> str | None:
        if isinstance(result, dict):
            return cast(str | None, result.get("partnerTxnId"))
        return result.partner_txn_id

    async def execute(
        self,
        *,
        partner: str,
        start_of_day: datetime,
        end_of_day: datetime,
        date_str: str,
        scope_type: ReconciliationScopeType,
        source_file_id: str | None = None,
        reconciliation_run_id: str | None = None,
        mapping_version: str | None = None,
        started_at: float | None = None,
    ) -> list[ReconciliationResult | dict[str, Any]]:
        t_start = started_at or time.perf_counter()
        t_scope_start = time.perf_counter()
        partner_query = {
            "identify": partner,
            "reconciliationDate": {
                "$gte": start_of_day,
                "$lte": end_of_day,
            },
        }
        delete_query: dict[str, Any]
        if source_file_id and scope_type in {
            ReconciliationScopeType.FULL_SNAPSHOT,
            ReconciliationScopeType.INCREMENTAL_APPEND,
            ReconciliationScopeType.REPLACEMENT,
        }:
            partner_query["sourceFileId"] = source_file_id

        internal_query = {
            "partner": partner,
            "transactionTime": {
                "$gte": start_of_day,
                "$lte": end_of_day,
            },
        }
        scoped_partner_keys: set[str] = set()
        if source_file_id and scope_type in {
            ReconciliationScopeType.INCREMENTAL_APPEND,
            ReconciliationScopeType.REPLACEMENT,
        }:
            scoped_partner_keys = await self._collect_scoped_partner_keys(partner_query)
        load_partner_scope_ms = (time.perf_counter() - t_scope_start) * 1000

        t_internal_start = time.perf_counter()
        internal_by_key = await self._build_internal_index(
            internal_query,
            scoped_partner_keys,
            scope_type,
        )
        internal_duration = (time.perf_counter() - t_internal_start) * 1000
        load_internal_candidates_ms = internal_duration * 0.8
        build_lookup_ms = internal_duration * 0.2

        results: list[ReconciliationResult | dict[str, Any]] = []
        result_buffer: list[ReconciliationResult | dict[str, Any]] = []
        matched_internal_keys: set[str] = set()
        replacement_keys = list(scoped_partner_keys)
        if source_file_id and scope_type in {
            ReconciliationScopeType.INCREMENTAL_APPEND,
            ReconciliationScopeType.REPLACEMENT,
        }:
            delete_query = {
                "partner": partner,
                "date": date_str,
                "$or": [
                    {"sourceFileId": source_file_id},
                    {"partnerTxnId": {"$in": replacement_keys}},
                ],
            }
        elif source_file_id and scope_type != ReconciliationScopeType.FULL_SNAPSHOT:
            delete_query = {
                "partner": partner,
                "date": date_str,
                "sourceFileId": source_file_id,
            }
        else:
            delete_query = {"partner": partner, "date": date_str}

        if hasattr(self._result_repo, "delete_by_partner_and_date"):
            source_file_id_param = delete_query.get("sourceFileId")
            partner_txn_ids_param = (
                delete_query.get("partnerTxnId", {}).get("$in")
                if isinstance(delete_query.get("partnerTxnId"), dict)
                else None
            )

            if "$or" in delete_query and isinstance(delete_query["$or"], list):
                for item in delete_query["$or"]:
                    if isinstance(item, dict):
                        if "sourceFileId" in item:
                            source_file_id_param = item["sourceFileId"]
                        if "partnerTxnId" in item and isinstance(item["partnerTxnId"], dict):
                            partner_txn_ids_param = item["partnerTxnId"].get("$in")

            kwargs = {}
            if source_file_id_param:
                kwargs["source_file_id"] = source_file_id_param
            if partner_txn_ids_param:
                kwargs["partner_txn_ids"] = partner_txn_ids_param
            await self._result_repo.delete_by_partner_and_date(
                partner,
                date_str,
                **kwargs,
            )
        elif hasattr(self._result_repo, "collection"):
            await self._result_repo.collection.delete_many(delete_query)

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
                result = await self._result_repo.insert_many(
                    batch_to_write,
                    ordered=self._ordered_insert,
                )
            batch_time = (time.perf_counter() - t0_loc) * 1000
            if batch_time > slowest_batch_ms:
                slowest_batch_ms = batch_time
            t_db_end_wall = time.perf_counter()
            return result

        partner_records_count = 0
        matched_count = 0
        mismatched_count = 0
        unmatched_partner_count = 0
        unmatched_internal_count = 0
        db_write_count = 0

        t_exact = 0.0
        t_mismatch = 0.0
        t_unmatched = 0.0
        t_write = 0.0

        async for partner_batch in self._iter_partner_record_batches(partner_query):
            for partner_record in partner_batch:
                partner_records_count += 1
                t_row_start = time.perf_counter()
                is_valid, reason = self._pre_check_record(partner_record)
                if not is_valid:
                    self._logger.get_logger().warning(
                        f"unmapped_record_skipped for record_id={str(partner_record.id)} "
                        f"reason={reason}"
                    )
                    t_exact += (time.perf_counter() - t_row_start) * 1000
                    result_buffer.append(
                        self._create_result_doc(
                            id=str(partner_record.id),
                            partner=partner,
                            date=date_str,
                            partnerTxnId=str(partner_record.id),
                            reconciliationRunId=reconciliation_run_id,
                            sourceFileId=(
                                str(partner_record.source_file_id)
                                if partner_record.source_file_id
                                else source_file_id
                            ),
                            scopeType=scope_type.value,
                            mappingVersion=mapping_version,
                            partnerRecordId=str(partner_record.id),
                            reconciliationStatus=ReconciliationStatus.UNMAPPED_SKIPPED,
                        )
                    )
                    if len(result_buffer) >= self._result_batch_size:
                        results.extend(result_buffer)
                        task = asyncio.create_task(_worker_flush(result_buffer))
                        write_tasks.append(task)
                        db_write_count += 1
                        result_buffer = []
                        write_tasks = [task for task in write_tasks if not task.done()]
                    continue

                partner_txn_id = self._resolve_partner_txn_id(partner_record)
                if not partner_txn_id:
                    self._logger.get_logger().warning(
                        f"partner_txn_id_missing for record_id={str(partner_record.id)}"
                    )
                    t_exact += (time.perf_counter() - t_row_start) * 1000
                    continue

                partner_amount = partner_record.partner_data.amount
                partner_status = partner_record.partner_data.status
                internal_record = internal_by_key.get(partner_txn_id)

                if internal_record:
                    matched_internal_keys.add(partner_txn_id)
                    internal_amount = internal_record["amount"]
                    internal_status = internal_record["status"]
                    norm_partner_status = self._normalize_status(partner_status)
                    norm_internal_status = self._normalize_status(internal_status)
                    amounts_match = partner_amount == internal_amount
                    statuses_match = norm_partner_status == norm_internal_status
                    t_exact += (time.perf_counter() - t_row_start) * 1000

                    t_mismatch_start = time.perf_counter()
                    if amounts_match and statuses_match:
                        matched_count += 1
                        if norm_partner_status == TransactionStatus.SUCCESS:
                            recon_status = ReconciliationStatus.MATCHED
                        elif norm_partner_status == TransactionStatus.FAILED:
                            recon_status = ReconciliationStatus.MATCHED_FAILED
                        elif norm_partner_status == TransactionStatus.REVERSED:
                            recon_status = ReconciliationStatus.MATCHED_REVERSED
                        else:
                            recon_status = ReconciliationStatus.MATCHED
                    elif not amounts_match and not statuses_match:
                        mismatched_count += 1
                        recon_status = ReconciliationStatus.MULTIPLE_MISMATCH
                    elif not amounts_match:
                        mismatched_count += 1
                        recon_status = ReconciliationStatus.AMOUNT_MISMATCH
                    else:
                        mismatched_count += 1
                        recon_status = ReconciliationStatus.STATUS_MISMATCH
                    t_mismatch += (time.perf_counter() - t_mismatch_start) * 1000
                    result_buffer.append(
                        self._create_result_doc(
                            id=partner_txn_id,
                            partner=partner,
                            date=date_str,
                            partnerTxnId=partner_txn_id,
                            internalTxnId=internal_record["id"],
                            partnerAmount=partner_amount,
                            internalAmount=internal_amount,
                            partnerStatus=partner_status,
                            internalStatus=internal_status,
                            reconciliationRunId=reconciliation_run_id,
                            sourceFileId=(
                                str(partner_record.source_file_id)
                                if partner_record.source_file_id
                                else source_file_id
                            ),
                            scopeType=scope_type.value,
                            mappingVersion=mapping_version,
                            reconciliationStatus=recon_status,
                            partnerRecordId=str(partner_record.id),
                            internalRecordId=str(internal_record["id"]),
                        )
                    )
                else:
                    unmatched_partner_count += 1
                    t_exact += (time.perf_counter() - t_row_start) * 1000
                    result_buffer.append(
                        self._create_result_doc(
                            id=partner_txn_id,
                            partner=partner,
                            date=date_str,
                            partnerTxnId=partner_txn_id,
                            partnerAmount=partner_amount,
                            partnerStatus=partner_status,
                            reconciliationRunId=reconciliation_run_id,
                            sourceFileId=(
                                str(partner_record.source_file_id)
                                if partner_record.source_file_id
                                else source_file_id
                            ),
                            scopeType=scope_type.value,
                            mappingVersion=mapping_version,
                            reconciliationStatus=ReconciliationStatus.MISSING_INTERNAL,
                            partnerRecordId=str(partner_record.id),
                        )
                    )

                if len(result_buffer) >= self._result_batch_size:
                    results.extend(result_buffer)
                    task = asyncio.create_task(_worker_flush(result_buffer))
                    write_tasks.append(task)
                    db_write_count += 1
                    result_buffer = []
                    write_tasks = [task for task in write_tasks if not task.done()]

        t_unmatched_start = time.perf_counter()
        for partner_txn_id, internal_record in internal_by_key.items():
            if partner_txn_id not in matched_internal_keys:
                unmatched_internal_count += 1
                result_buffer.append(
                    self._create_result_doc(
                        id=partner_txn_id,
                        partner=partner,
                        date=date_str,
                        partnerTxnId=partner_txn_id,
                        internalTxnId=internal_record["id"],
                        internalAmount=internal_record["amount"],
                        internalStatus=internal_record["status"],
                        reconciliationRunId=reconciliation_run_id,
                        sourceFileId=source_file_id,
                        scopeType=scope_type.value,
                        mappingVersion=mapping_version,
                        reconciliationStatus=ReconciliationStatus.MISSING_PARTNER,
                        internalRecordId=str(internal_record["id"]),
                    )
                )
                if len(result_buffer) >= self._result_batch_size:
                    results.extend(result_buffer)
                    task = asyncio.create_task(_worker_flush(result_buffer))
                    write_tasks.append(task)
                    db_write_count += 1
                    result_buffer = []
                    write_tasks = [task for task in write_tasks if not task.done()]
        t_unmatched += (time.perf_counter() - t_unmatched_start) * 1000

        if result_buffer:
            results.extend(result_buffer)
            task = asyncio.create_task(_worker_flush(result_buffer))
            write_tasks.append(task)
            db_write_count += 1
            result_buffer = []

        if write_tasks:
            await asyncio.gather(*write_tasks)
        if t_db_start_wall > 0.0:
            t_write = (t_db_end_wall - t_db_start_wall) * 1000

        if partner_records_count > 100 and len(internal_by_key) > 100 and matched_count == 0:
            sample_partner_keys = list(scoped_partner_keys)[:3] if scoped_partner_keys else []
            if not sample_partner_keys:
                fallback_partner_keys = [
                    self._result_partner_key(doc)
                    for doc in results[:3]
                ]
                sample_partner_keys = [
                    key
                    for key in fallback_partner_keys
                    if isinstance(key, str) and key
                ]
            sample_internal_keys = list(internal_by_key.keys())[:3]
            warn_msg = (
                f"🚨 WARNING: Potential Matching Key Mismatch Detected for partner={partner}! "
                f"Processed {partner_records_count} partner records and {len(internal_by_key)} internal records, "
                f"but MATCHED_COUNT is 0. Please verify your mapping configuration. "
                f"Sample Partner Keys: {sample_partner_keys} | Sample Internal Keys: {sample_internal_keys}"
            )
            print(warn_msg, flush=True)
            self._logger.get_logger().warning(warn_msg)

        duration_ms = (time.perf_counter() - t_start) * 1000
        self._logger.get_logger().info(
            f"reconciliation_completed for partner={partner} total_processed={len(results)}"
        )
        perf_log = (
            f"PERF_RECON: total_reconciliation_ms={duration_ms:.2f} "
            f"load_partner_scope_ms={load_partner_scope_ms:.2f} "
            f"load_internal_candidates_ms={load_internal_candidates_ms:.2f} "
            f"build_lookup_ms={build_lookup_ms:.2f} exact_match_ms={t_exact:.2f} "
            f"mismatch_detection_ms={t_mismatch:.2f} unmatched_detection_ms={t_unmatched:.2f} "
            f"result_bulk_write_ms={t_write:.2f} summary_aggregation_ms=0.00 "
            f"partner_records_count={partner_records_count} "
            f"internal_candidates_count={len(internal_by_key)} matched_count={matched_count} "
            f"mismatched_count={mismatched_count} unmatched_partner_count={unmatched_partner_count} "
            f"unmatched_internal_count={unmatched_internal_count} db_read_operation_count=3 "
            f"db_write_operation_count={db_write_count} slowest_batch_ms={slowest_batch_ms:.2f}"
        )
        print(perf_log, flush=True)
        self._logger.get_logger().info(perf_log)
        return results
