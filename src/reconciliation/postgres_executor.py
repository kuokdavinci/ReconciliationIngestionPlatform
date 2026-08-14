"""PostgreSQL execution boundary for reconciliation."""

import time
from datetime import datetime
from typing import Any
from uuid import UUID

from src.core.enums import ReconciliationScopeType
from src.domain.reconciliation.models import ReconciliationResult
from src.infrastructure.postgres.reconciliation_result_repository import (
    row_to_reconciliation_result,
)
from src.logging import get_structured_logger


class PostgresReconciliationExecutor:
    """Run reconciliation through the PostgreSQL set-based query path."""

    def __init__(self, result_repo: Any, logger: Any | None = None) -> None:
        self._result_repo = result_repo
        self._logger = logger or get_structured_logger()

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
    ) -> list[ReconciliationResult]:
        """Execute the unchanged SQL reconciliation transaction and map rows."""
        from sqlalchemy import and_, select, text
        from sqlalchemy.ext.asyncio import AsyncSession

        from src.infrastructure.persistence.postgres_schema import (
            ReconciliationResultTable,
        )

        delete_sql = self._delete_sql(source_file_id, scope_type)
        match_insert_sql = """
        INSERT INTO reconciliation_result (
            id, partner, date, partner_txn_id, internal_txn_id,
            partner_amount, internal_amount, partner_status, internal_status,
            reconciliation_status, reconciliation_run_id, source_file_id,
            scope_type, mapping_version, partner_record_id, internal_record_id, created_at
        )
        WITH normalized_partner AS (
            SELECT
                p.*,
                COALESCE(
                    NULLIF(BTRIM(p.partner_trace), ''),
                    NULLIF(BTRIM(p.partner_metadata->>'vspTransId'), ''),
                    NULLIF(BTRIM(p.partner_id), '')
                ) AS reconciliation_key,
                CASE
                    WHEN LOWER(BTRIM(p.partner_status)) IN ('success', 'thành công', 'matched') THEN 'SUCCESS'
                    WHEN LOWER(BTRIM(p.partner_status)) IN ('fail', 'failed', 'thất bại') THEN 'FAILED'
                    WHEN LOWER(BTRIM(p.partner_status)) IN ('reversed', 'hoàn tiền') THEN 'REVERSED'
                    ELSE 'PENDING'
                END AS normalized_status
            FROM partner_transaction p
            WHERE p.identify = :partner
              AND p.reconciliation_date >= :start_of_day
              AND p.reconciliation_date <= :end_of_day
              AND (
                  CAST(:source_file_id_uuid AS UUID) IS NULL
                  OR p.source_file_id = CAST(:source_file_id_uuid AS UUID)
              )
        ),
        normalized_internal AS (
            SELECT
                i.*,
                NULLIF(BTRIM(i.partner_txn_id), '') AS reconciliation_key,
                CASE
                    WHEN LOWER(BTRIM(i.status)) IN ('success', 'thành công', 'matched') THEN 'SUCCESS'
                    WHEN LOWER(BTRIM(i.status)) IN ('fail', 'failed', 'thất bại') THEN 'FAILED'
                    WHEN LOWER(BTRIM(i.status)) IN ('reversed', 'hoàn tiền') THEN 'REVERSED'
                    ELSE 'PENDING'
                END AS normalized_status
            FROM internal_transaction i
            WHERE i.partner = :partner
              AND i.transaction_time >= :start_of_day
              AND i.transaction_time <= :end_of_day
              AND (
                  CAST(:source_file_id_uuid AS UUID) IS NULL
                  OR CAST(:scope_type AS VARCHAR) = 'FULL_SNAPSHOT'
                  OR NULLIF(BTRIM(i.partner_txn_id), '') IN (
                      SELECT reconciliation_key
                      FROM normalized_partner
                      WHERE source_file_id = CAST(:source_file_id_uuid AS UUID)
                  )
              )
        )
        SELECT
            CAST(gen_random_uuid() AS VARCHAR) AS id,
            :partner AS partner,
            :date_str AS date,
            COALESCE(p.reconciliation_key, i.partner_txn_id, p.partner_id) AS partner_txn_id,
            i.id AS internal_txn_id,
            p.partner_amount AS partner_amount,
            i.amount AS internal_amount,
            p.partner_status AS partner_status,
            i.status AS internal_status,
            CASE
                WHEN p.id IS NOT NULL AND i.id IS NOT NULL THEN
                    CASE
                        WHEN p.partner_amount = i.amount AND p.normalized_status = i.normalized_status THEN
                            CASE
                                WHEN p.normalized_status = 'SUCCESS' THEN 'MATCHED'
                                WHEN p.normalized_status = 'FAILED' THEN 'MATCHED_FAILED'
                                WHEN p.normalized_status = 'REVERSED' THEN 'MATCHED_REVERSED'
                                ELSE 'MATCHED'
                            END
                        WHEN p.partner_amount != i.amount AND p.normalized_status != i.normalized_status THEN 'MULTIPLE_MISMATCH'
                        WHEN p.partner_amount != i.amount THEN 'AMOUNT_MISMATCH'
                        ELSE 'STATUS_MISMATCH'
                    END
                WHEN p.id IS NOT NULL THEN 'MISSING_INTERNAL'
                ELSE 'MISSING_PARTNER'
            END AS reconciliation_status,
            CAST(:reconciliation_run_id AS VARCHAR) AS reconciliation_run_id,
            COALESCE(CAST(p.source_file_id AS VARCHAR), CAST(:source_file_id AS VARCHAR)) AS source_file_id,
            CAST(:scope_type AS VARCHAR) AS scope_type,
            CAST(:mapping_version AS VARCHAR) AS mapping_version,
            CAST(p.id AS VARCHAR) AS partner_record_id,
            i.id AS internal_record_id,
            NOW() AS created_at
        FROM normalized_partner p
        FULL OUTER JOIN normalized_internal i
          ON p.reconciliation_key = i.reconciliation_key
        """

        params = {
            "partner": partner,
            "date_str": date_str,
            "start_of_day": start_of_day.replace(tzinfo=None),
            "end_of_day": end_of_day.replace(tzinfo=None),
            "reconciliation_run_id": reconciliation_run_id,
            "source_file_id": source_file_id,
            "source_file_id_uuid": UUID(source_file_id) if source_file_id else None,
            "scope_type": scope_type.value,
            "mapping_version": mapping_version,
        }

        async with self._result_repo.engine.begin() as conn:
            await conn.execute(text(delete_sql), params)
            await conn.execute(text(match_insert_sql), params)

        async with AsyncSession(self._result_repo.engine) as session:
            conditions = [
                ReconciliationResultTable.partner == partner,
                ReconciliationResultTable.date == date_str,
            ]
            if reconciliation_run_id:
                conditions.append(
                    ReconciliationResultTable.reconciliation_run_id
                    == reconciliation_run_id
                )
            elif source_file_id:
                conditions.append(
                    ReconciliationResultTable.source_file_id == source_file_id
                )

            stmt = select(ReconciliationResultTable).where(and_(*conditions))
            result = await session.execute(stmt)
            rows = result.scalars().all()
            results = [row_to_reconciliation_result(row) for row in rows]

        duration_ms = self._duration_ms(started_at)
        self._logger.get_logger().info(
            f"reconciliation_completed (SQL mode) for partner={partner} "
            f"total_processed={len(results)} duration_ms={duration_ms:.2f}"
        )
        return results

    @staticmethod
    def _duration_ms(started_at: float | None) -> float:
        return (time.perf_counter() - started_at) * 1000 if started_at else 0.0

    @staticmethod
    def _delete_sql(
        source_file_id: str | None,
        scope_type: ReconciliationScopeType,
    ) -> str:
        if source_file_id and scope_type in {
            ReconciliationScopeType.INCREMENTAL_APPEND,
            ReconciliationScopeType.REPLACEMENT,
        }:
            return """
            DELETE FROM reconciliation_result
            WHERE partner = :partner AND date = :date_str
              AND (source_file_id = :source_file_id OR partner_txn_id IN (
                  SELECT COALESCE(
                      NULLIF(BTRIM(partner_trace), ''),
                      NULLIF(BTRIM(partner_metadata->>'vspTransId'), ''),
                      NULLIF(BTRIM(partner_id), '')
                  )
                  FROM partner_transaction
                  WHERE identify = :partner AND source_file_id = :source_file_id_uuid
              ));
            """
        if source_file_id and scope_type != ReconciliationScopeType.FULL_SNAPSHOT:
            return """
            DELETE FROM reconciliation_result
            WHERE partner = :partner AND date = :date_str AND source_file_id = :source_file_id;
            """
        return """
        DELETE FROM reconciliation_result
        WHERE partner = :partner AND date = :date_str;
        """
