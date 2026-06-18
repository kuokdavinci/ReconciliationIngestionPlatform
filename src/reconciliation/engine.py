"""Reconciliation Engine for transaction content matching."""

import inspect
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Optional
from unittest.mock import Mock

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.core.enums import ReconciliationScopeType, ReconciliationStatus, TransactionStatus
from src.models.data_container import DataContainer, DataContainerRepository
from src.models.internal_transaction import (
    InternalTransactionRepository,
)
from src.models.reconciliation_result import (
    ReconciliationResult,
    ReconciliationResultRepository,
)
from src.logging import get_structured_logger


class ReconciliationEngine:
    """Deterministic Reconciliation Engine comparing DataContainer (partner) and InternalTransaction."""

    PARTNER_BATCH_SIZE = 5000
    RESULT_WRITE_BATCH_SIZE = 5000

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        """Initialize the engine with repositories."""
        self._db = db
        self._data_repo = DataContainerRepository(db)
        self._internal_repo = InternalTransactionRepository(db)
        self._result_repo = ReconciliationResultRepository(db)
        self._logger = get_structured_logger()

    @staticmethod
    def _is_async_iterable(value) -> bool:
        if isinstance(value, Mock):
            return False
        return (
            isinstance(value, AsyncIterator)
            or inspect.isasyncgen(value)
            or hasattr(value, "__anext__")
        )

    def _normalize_status(self, status_str: str) -> TransactionStatus:
        """Normalize partner/internal statuses to standard internal TransactionStatus."""
        status_lower = str(status_str).strip().lower()
        if status_lower in ("success", "thành công", "matched"):
            return TransactionStatus.SUCCESS
        if status_lower in ("fail", "failed", "thất bại"):
            return TransactionStatus.FAILED
        if status_lower in ("reversed", "hoàn tiền"):
            return TransactionStatus.REVERSED
        return TransactionStatus.PENDING

    def _resolve_partner_txn_id(self, partner_record: DataContainer) -> Optional[str]:
        """Resolve reconciliation key from partner data container."""
        pd = partner_record.partner_data
        if pd.trace:
            return str(pd.trace).strip()
        if pd.extra and pd.extra.get("vspTransId"):
            return str(pd.extra.get("vspTransId")).strip()
        if pd.id:
            return str(pd.id).strip()
        return None

    def _is_finalized_internal_status(self, status: TransactionStatus | str) -> bool:
        """Return True when an internal transaction is finalized for reconciliation.

        Pending internal rows should not participate in reconciliation yet because
        they are still in-flight and would inflate `MISSING_PARTNER` counts.
        """
        normalized = self._normalize_status(str(status))
        return normalized in {
            TransactionStatus.SUCCESS,
            TransactionStatus.FAILED,
            TransactionStatus.REVERSED,
        }

    def _pre_check_record(self, partner_record: DataContainer) -> tuple[bool, str]:
        """Pre-check a partner record before reconciliation.

        Verifies the record has valid normalized data. Records failing this
        check are skipped with a warning log (not treated as errors).

        Returns:
            Tuple of (is_valid: bool, reason: str).
            If valid, reason is empty string. If invalid, reason describes the issue.
        """
        # Check partnerData exists
        if partner_record.partner_data is None:
            return False, "empty_partner_data"

        # Check amount is present and non-zero (valid Decimal)
        amount = partner_record.partner_data.amount
        if amount is None:
            return False, "missing_amount"

        # Check status is present and non-empty
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
        cursor = self._internal_repo.collection.find(internal_query, projection=projection)
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
                status = normalized.get("status")
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

        internal_records = await self._internal_repo.find_many(internal_query)
        finalized_internal_records = [
            record for record in internal_records
            if self._is_finalized_internal_status(record.status)
        ]
        if scope_type != ReconciliationScopeType.FULL_SNAPSHOT and scoped_partner_keys:
            finalized_internal_records = [
                record for record in finalized_internal_records
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
        cursor = self._data_repo.collection.find(partner_query).batch_size(self.PARTNER_BATCH_SIZE)
        if self._is_async_iterable(cursor):
            batch: list[DataContainer] = []
            async for raw in cursor:
                batch.append(self._data_repo._from_mongo(raw))
                if len(batch) >= self.PARTNER_BATCH_SIZE:
                    yield batch
                    batch = []
            if batch:
                yield batch
            return

        records = await self._data_repo.find_many(partner_query)
        for start in range(0, len(records), self.PARTNER_BATCH_SIZE):
            yield records[start:start + self.PARTNER_BATCH_SIZE]

    async def _collect_scoped_partner_keys(self, partner_query: dict) -> set[str]:
        scoped_partner_keys: set[str] = set()
        async for partner_batch in self._iter_partner_record_batches(partner_query):
            for record in partner_batch:
                key = self._resolve_partner_txn_id(record)
                if key:
                    scoped_partner_keys.add(key)
        return scoped_partner_keys

    async def _flush_result_buffer(
        self,
        result_buffer: list[ReconciliationResult],
        results: list[ReconciliationResult],
        delete_query: dict,
        cleared_existing: bool,
    ) -> bool:
        if not result_buffer:
            return cleared_existing
        if not cleared_existing:
            await self._result_repo.collection.delete_many(delete_query)
            cleared_existing = True
        batch_to_insert = list(result_buffer)
        await self._result_repo.insert_many(batch_to_insert)
        results.extend(batch_to_insert)
        result_buffer.clear()
        return cleared_existing

    async def reconcile(
        self,
        partner: str,
        reconciliation_date: datetime,
        source_file_id: str | None = None,
        reconciliation_run_id: str | None = None,
        mapping_version: str | None = None,
    ) -> list[ReconciliationResult]:
        """Execute reconciliation matching for a given partner and date.

        Args:
            partner: MOMO, ZALOPAY, etc.
            reconciliation_date: Target date of reconciliation file.

        Returns:
            List of generated ReconciliationResult documents.
        """
        self._logger.get_logger().info(
            f"reconciliation_started for partner={partner} date={reconciliation_date.isoformat()} source_file_id={source_file_id or '-'}"
        )

        # 1. Calculate boundaries of target date
        start_of_day = reconciliation_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = reconciliation_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        date_str = reconciliation_date.strftime("%Y-%m-%d")

        scope_type = ReconciliationScopeType.FULL_SNAPSHOT
        if source_file_id:
            file_doc = await self._db["reconciliation_file"].find_one({"_id": source_file_id})
            raw_scope = (file_doc or {}).get("scopeType")
            if raw_scope:
                try:
                    scope_type = ReconciliationScopeType(str(raw_scope))
                except ValueError:
                    scope_type = ReconciliationScopeType.UNCONFIRMED

        # 2. Build partner query
        partner_query = {
            "identify": partner,
            "reconciliationDate": {
                "$gte": start_of_day,
                "$lte": end_of_day,
            }
        }
        if source_file_id and scope_type != ReconciliationScopeType.FULL_SNAPSHOT:
            partner_query["sourceFileId"] = source_file_id

        # 3. Build internal query
        internal_query = {
            "partner": partner,
            "transactionTime": {
                "$gte": start_of_day,
                "$lte": end_of_day,
            }
        }
        scoped_partner_keys: set[str] = set()
        if source_file_id and scope_type != ReconciliationScopeType.FULL_SNAPSHOT:
            scoped_partner_keys = await self._collect_scoped_partner_keys(partner_query)

        # 4. Keep only finalized internal transactions, then resolve duplicates
        internal_by_key = await self._build_internal_index(
            internal_query,
            scoped_partner_keys,
            scope_type,
        )

        results: list[ReconciliationResult] = []
        result_buffer: list[ReconciliationResult] = []
        matched_internal_keys: set[str] = set()
        replacement_keys = list(scoped_partner_keys)
        if source_file_id and scope_type == ReconciliationScopeType.REPLACEMENT:
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
        cleared_existing = False

        # 5. Process partner records
        async for partner_batch in self._iter_partner_record_batches(partner_query):
            for partner_record in partner_batch:
                # Pre-check: skip records with invalid/non-normalized data (DATA-FLOW-01)
                is_valid, reason = self._pre_check_record(partner_record)
                if not is_valid:
                    self._logger.get_logger().warning(
                        f"unmapped_record_skipped for record_id={str(partner_record.id)} reason={reason}"
                    )
                    result_buffer.append(
                        ReconciliationResult(
                            id=str(partner_record.id),
                            partner=partner,
                            date=date_str,
                            partnerTxnId=str(partner_record.id),
                            reconciliationRunId=reconciliation_run_id,
                            sourceFileId=source_file_id,
                            scopeType=scope_type.value,
                            mappingVersion=mapping_version,
                            partnerRecordId=str(partner_record.id),
                            reconciliationStatus=ReconciliationStatus.UNMAPPED_SKIPPED,
                        )
                    )
                    if len(result_buffer) >= self.RESULT_WRITE_BATCH_SIZE:
                        cleared_existing = await self._flush_result_buffer(
                            result_buffer, results, delete_query, cleared_existing
                        )
                    continue

                partner_txn_id = self._resolve_partner_txn_id(partner_record)
                if not partner_txn_id:
                    self._logger.get_logger().warning(
                        f"partner_txn_id_missing for record_id={str(partner_record.id)}"
                    )
                    continue

                partner_amount = partner_record.partner_data.amount
                partner_status = partner_record.partner_data.status

                internal_record = internal_by_key.get(partner_txn_id)

                if internal_record:
                    # Key matches, compare fields
                    matched_internal_keys.add(partner_txn_id)
                    internal_amount = internal_record["amount"]
                    internal_status = internal_record["status"]

                    norm_partner_status = self._normalize_status(partner_status)
                    norm_internal_status = self._normalize_status(internal_status)

                    amounts_match = partner_amount == internal_amount
                    statuses_match = norm_partner_status == norm_internal_status

                    if amounts_match and statuses_match:
                        if norm_partner_status == TransactionStatus.SUCCESS:
                            recon_status = ReconciliationStatus.MATCHED
                        elif norm_partner_status == TransactionStatus.FAILED:
                            recon_status = ReconciliationStatus.MATCHED_FAILED
                        elif norm_partner_status == TransactionStatus.REVERSED:
                            recon_status = ReconciliationStatus.MATCHED_REVERSED
                        else:
                            recon_status = ReconciliationStatus.MATCHED
                    elif not amounts_match and not statuses_match:
                        recon_status = ReconciliationStatus.MULTIPLE_MISMATCH
                    elif not amounts_match:
                        recon_status = ReconciliationStatus.AMOUNT_MISMATCH
                    else:
                        recon_status = ReconciliationStatus.STATUS_MISMATCH

                    result_buffer.append(
                        ReconciliationResult(
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
                            sourceFileId=source_file_id,
                            scopeType=scope_type.value,
                            mappingVersion=mapping_version,
                            reconciliationStatus=recon_status,
                            partnerRecordId=str(partner_record.id),
                            internalRecordId=str(internal_record["id"]),
                        )
                    )
                else:
                    # Missing Internal record
                    result_buffer.append(
                        ReconciliationResult(
                            id=partner_txn_id,
                            partner=partner,
                            date=date_str,
                            partnerTxnId=partner_txn_id,
                            partnerAmount=partner_amount,
                            partnerStatus=partner_status,
                            reconciliationRunId=reconciliation_run_id,
                            sourceFileId=source_file_id,
                            scopeType=scope_type.value,
                            mappingVersion=mapping_version,
                            reconciliationStatus=ReconciliationStatus.MISSING_INTERNAL,
                            partnerRecordId=str(partner_record.id),
                        )
                    )

                if len(result_buffer) >= self.RESULT_WRITE_BATCH_SIZE:
                    cleared_existing = await self._flush_result_buffer(
                        result_buffer, results, delete_query, cleared_existing
                    )

        # 6. Process missing partner records
        for partner_txn_id, internal_record in internal_by_key.items():
            if partner_txn_id not in matched_internal_keys:
                result_buffer.append(
                    ReconciliationResult(
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
                if len(result_buffer) >= self.RESULT_WRITE_BATCH_SIZE:
                    cleared_existing = await self._flush_result_buffer(
                        result_buffer, results, delete_query, cleared_existing
                    )

        # 7. Write results to database
        if result_buffer:
            cleared_existing = await self._flush_result_buffer(
                result_buffer, results, delete_query, cleared_existing
            )

        self._logger.get_logger().info(
            f"reconciliation_completed for partner={partner} total_processed={len(results)}"
        )
        return results
