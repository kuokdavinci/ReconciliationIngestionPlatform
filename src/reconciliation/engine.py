"""Reconciliation entry point and explicit backend composition."""

import time
from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.config.settings import settings
from src.core.business_day import business_date, utc_business_day_bounds
from src.core.enums import ReconciliationScopeType
from src.domain.reconciliation.ports import (
    InternalTransactionReader,
    PartnerTransactionReader,
    ReconciliationBackend,
    ReconciliationExecutor,
    ReconciliationOutput,
    ReconciliationResultWriter,
)
from src.logging import StructuredLogger, get_structured_logger
from src.reconciliation.document_executor import DocumentReconciliationExecutor
from src.reconciliation.postgres_executor import PostgresReconciliationExecutor


class ReconciliationEngine:
    """Public reconciliation entry point with explicit storage execution."""

    PARTNER_BATCH_SIZE = 100000
    RESULT_WRITE_BATCH_SIZE = 100000

    def __init__(
        self,
        db: AsyncIOMotorDatabase,
        fast_mode: bool = False,
        result_batch_size: int | None = None,
        write_workers: int | None = None,
        ordered_insert: bool | None = None,
        partner_batch_size: int | None = None,
        data_repo: PartnerTransactionReader | None = None,
        internal_repo: InternalTransactionReader | None = None,
        result_repo: ReconciliationResultWriter | None = None,
        *,
        backend: ReconciliationBackend = "postgres",
        executor: ReconciliationExecutor | None = None,
    ) -> None:
        """Initialize the engine with repositories and an explicit executor."""
        if data_repo is None:
            from src.infrastructure.partner_transaction.repository import DataContainerRepository

            data_repo = DataContainerRepository(db)
        if internal_repo is None:
            from src.infrastructure.postgres.internal_transaction_repository import (
                InternalTransactionRepository,
            )

            internal_repo = InternalTransactionRepository(db)
        if result_repo is None:
            from src.infrastructure.postgres.reconciliation_result_repository import (
                ReconciliationResultRepository,
            )

            result_repo = ReconciliationResultRepository(db)

        self._db = db
        self._data_repo = data_repo
        self._internal_repo = internal_repo
        self._result_repo = result_repo
        self._logger: StructuredLogger = get_structured_logger()
        self.fast_mode = fast_mode
        self._partner_batch_size = (
            partner_batch_size
            if partner_batch_size is not None
            else settings.recon_partner_batch_size
        )
        self._result_batch_size = (
            result_batch_size
            if result_batch_size is not None
            else settings.recon_result_batch_size
        )
        self._write_workers = (
            write_workers
            if write_workers is not None
            else settings.recon_result_write_workers
        )
        self._ordered_insert = (
            ordered_insert
            if ordered_insert is not None
            else settings.recon_result_ordered_insert
        )
        self._backend = backend
        self._executor = executor or self._build_executor(backend)

    def _build_executor(self, backend: ReconciliationBackend) -> ReconciliationExecutor:
        if backend == "postgres":
            return PostgresReconciliationExecutor(
                result_repo=self._result_repo,
                logger=self._logger,
            )
        if backend == "document":
            return DocumentReconciliationExecutor(
                data_repo=self._data_repo,
                internal_repo=self._internal_repo,
                result_repo=self._result_repo,
                fast_mode=self.fast_mode,
                partner_batch_size=self._partner_batch_size,
                result_batch_size=self._result_batch_size,
                write_workers=self._write_workers,
                ordered_insert=self._ordered_insert,
                logger=self._logger,
            )
        raise ValueError(f"Unsupported reconciliation backend: {backend}")

    @staticmethod
    def _business_day_bounds(reconciliation_date: datetime) -> tuple[datetime, datetime]:
        """Return UTC-aware bounds for the configured business calendar day."""
        return utc_business_day_bounds(reconciliation_date)

    async def reconcile(
        self,
        partner: str,
        reconciliation_date: datetime,
        source_file_id: str | None = None,
        reconciliation_run_id: str | None = None,
        mapping_version: str | None = None,
    ) -> list[ReconciliationOutput]:
        """Execute reconciliation matching for a partner and business date."""
        t_start = time.perf_counter()
        self._logger.get_logger().info(
            f"reconciliation_started for partner={partner} "
            f"date={reconciliation_date.isoformat()} "
            f"source_file_id={source_file_id or '-'}"
        )

        start_of_day, end_of_day = self._business_day_bounds(reconciliation_date)
        date_str = business_date(reconciliation_date).isoformat()
        scope_type = await self._resolve_scope_type(source_file_id)
        return await self._executor.execute(
            partner=partner,
            start_of_day=start_of_day,
            end_of_day=end_of_day,
            date_str=date_str,
            scope_type=scope_type,
            source_file_id=source_file_id,
            reconciliation_run_id=reconciliation_run_id,
            mapping_version=mapping_version,
            started_at=t_start,
        )

    async def _resolve_scope_type(
        self,
        source_file_id: str | None,
    ) -> ReconciliationScopeType:
        scope_type = ReconciliationScopeType.FULL_SNAPSHOT
        if not source_file_id:
            return scope_type

        file_doc = await self._db["reconciliation_file"].find_one({"_id": source_file_id})
        raw_scope = (file_doc or {}).get("scopeType")
        if raw_scope:
            try:
                return ReconciliationScopeType(str(raw_scope))
            except ValueError:
                return ReconciliationScopeType.UNCONFIRMED
        return scope_type
