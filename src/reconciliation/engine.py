"""Reconciliation Engine for transaction content matching."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.core.enums import ReconciliationStatus, TransactionStatus
from src.models.data_container import DataContainer, DataContainerRepository
from src.models.internal_transaction import (
    InternalTransaction,
    InternalTransactionRepository,
)
from src.models.reconciliation_result import (
    ReconciliationResult,
    ReconciliationResultRepository,
)
from src.logging import get_structured_logger


class ReconciliationEngine:
    """Deterministic Reconciliation Engine comparing DataContainer (partner) and InternalTransaction."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        """Initialize the engine with repositories."""
        self._db = db
        self._data_repo = DataContainerRepository(db)
        self._internal_repo = InternalTransactionRepository(db)
        self._result_repo = ReconciliationResultRepository(db)
        self._logger = get_structured_logger()

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

    async def reconcile(self, partner: str, reconciliation_date: datetime) -> list[ReconciliationResult]:
        """Execute reconciliation matching for a given partner and date.

        Args:
            partner: MOMO, ZALOPAY, etc.
            reconciliation_date: Target date of reconciliation file.

        Returns:
            List of generated ReconciliationResult documents.
        """
        self._logger.get_logger().info(
            f"reconciliation_started for partner={partner} date={reconciliation_date.isoformat()}"
        )

        # 1. Calculate boundaries of target date
        start_of_day = reconciliation_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = reconciliation_date.replace(hour=23, minute=59, second=59, microsecond=999999)

        # 2. Fetch partner transactions
        partner_records = await self._data_repo.find_many({
            "identify": partner,
            "reconciliationDate": {
                "$gte": start_of_day,
                "$lte": end_of_day,
            }
        })

        # 3. Fetch internal transactions
        internal_records = await self._internal_repo.find_many({
            "partner": partner,
            "transactionTime": {
                "$gte": start_of_day,
                "$lte": end_of_day,
            }
        })

        # 4. Resolve duplicates in internal transactions (latest updated wins)
        internal_by_key: dict[str, InternalTransaction] = {}
        for record in internal_records:
            key = record.partner_txn_id.strip()
            if key not in internal_by_key:
                internal_by_key[key] = record
            else:
                existing = internal_by_key[key]
                if record.updated_at > existing.updated_at:
                    internal_by_key[key] = record

        results: list[ReconciliationResult] = []
        matched_internal_keys: set[str] = set()

        # 5. Process partner records
        for partner_record in partner_records:
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
                internal_amount = internal_record.amount
                internal_status = internal_record.status

                norm_partner_status = self._normalize_status(partner_status)
                norm_internal_status = self._normalize_status(internal_status)

                amounts_match = partner_amount == internal_amount
                statuses_match = norm_partner_status == norm_internal_status

                if amounts_match and statuses_match:
                    recon_status = ReconciliationStatus.MATCHED
                elif not amounts_match and not statuses_match:
                    recon_status = ReconciliationStatus.MULTIPLE_MISMATCH
                elif not amounts_match:
                    recon_status = ReconciliationStatus.AMOUNT_MISMATCH
                else:
                    recon_status = ReconciliationStatus.STATUS_MISMATCH

                result = ReconciliationResult(
                    id=partner_txn_id,
                    partnerTxnId=partner_txn_id,
                    internalTxnId=internal_record.id,
                    partnerAmount=partner_amount,
                    internalAmount=internal_amount,
                    partnerStatus=partner_status,
                    internalStatus=internal_status,
                    reconciliationStatus=recon_status,
                    partnerRecordId=str(partner_record.id),
                    internalRecordId=str(internal_record.id),
                )
                results.append(result)
            else:
                # Missing Internal record
                result = ReconciliationResult(
                    id=partner_txn_id,
                    partnerTxnId=partner_txn_id,
                    partnerAmount=partner_amount,
                    partnerStatus=partner_status,
                    reconciliationStatus=ReconciliationStatus.MISSING_INTERNAL,
                    partnerRecordId=str(partner_record.id),
                )
                results.append(result)

        # 6. Process missing partner records
        for partner_txn_id, internal_record in internal_by_key.items():
            if partner_txn_id not in matched_internal_keys:
                result = ReconciliationResult(
                    id=partner_txn_id,
                    partnerTxnId=partner_txn_id,
                    internalTxnId=internal_record.id,
                    internalAmount=internal_record.amount,
                    internalStatus=internal_record.status,
                    reconciliationStatus=ReconciliationStatus.MISSING_PARTNER,
                    internalRecordId=str(internal_record.id),
                )
                results.append(result)

        # 7. Write results to database
        if results:
            # Clean up old results for the same keys to ensure idempotency
            target_ids = [r.id for r in results]
            await self._result_repo.collection.delete_many({"_id": {"$in": target_ids}})
            await self._result_repo.insert_many(results)

        self._logger.get_logger().info(
            f"reconciliation_completed for partner={partner} total_processed={len(results)}"
        )
        return results
