"""PostgreSQL-backed reconciliation entry point."""

import time
from datetime import datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.core.utils import business_date, utc_business_day_bounds
from src.core.enums import ReconciliationScopeType
from src.domain.mapping.models import ReconciliationPolicy
from src.domain.reconciliation.ports import ReconciliationExecutor, ReconciliationOutput
from src.logging import StructuredLogger, get_structured_logger
from src.reconciliation.postgres_executor import PostgresReconciliationExecutor
from src.infrastructure.postgres.reconciliation_result_repository import (
    ReconciliationResultRepository,
)


class ReconciliationEngine:
    """Public reconciliation entry point backed by PostgreSQL."""

    def __init__(
        self,
        db: AsyncIOMotorDatabase,
        *,
        executor: ReconciliationExecutor | None = None,
        mapping_repository: Any | None = None,
    ) -> None:
        """Initialize the engine with the PostgreSQL executor."""
        self._db = db
        if mapping_repository is None:
            from src.infrastructure.mapping.config_repository import MappingConfigRepository

            mapping_repository = MappingConfigRepository(db)
        self._mapping_repository = mapping_repository
        self._logger: StructuredLogger = get_structured_logger()
        if executor is None:
            result_repo = ReconciliationResultRepository(db)
            executor = PostgresReconciliationExecutor(
                result_repo=result_repo,
                logger=self._logger,
            )
        self._executor = executor

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
        timestamp_policy = await self._resolve_timestamp_policy(partner, mapping_version)
        return await self._executor.execute(
            partner=partner,
            start_of_day=start_of_day,
            end_of_day=end_of_day,
            date_str=date_str,
            scope_type=scope_type,
            source_file_id=source_file_id,
            reconciliation_run_id=reconciliation_run_id,
            mapping_version=mapping_version,
            timestamp_policy=timestamp_policy,
            started_at=t_start,
        )

    async def _resolve_timestamp_policy(
        self, partner: str, mapping_version: str | None
    ) -> ReconciliationPolicy:
        if not mapping_version:
            return ReconciliationPolicy()
        try:
            config = await self._mapping_repository.find_by_version(partner, mapping_version)
        except Exception:
            # A legacy/incomplete config projection must not block reconciliation;
            # use the documented default until a valid versioned policy is available.
            config = None
        return getattr(config, "timestamp_policy", None) or ReconciliationPolicy()

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
