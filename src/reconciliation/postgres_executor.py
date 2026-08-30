"""PostgreSQL execution boundary for reconciliation."""

import time
from collections import Counter
from datetime import datetime
from typing import Any
from uuid import UUID

from src.core.enums import ReconciliationScopeType
from src.domain.mapping.models import ReconciliationPolicy
from src.domain.reconciliation.ports import ReconciliationOutput
from src.infrastructure.postgres.reconciliation_result_repository import (
    row_to_reconciliation_result,
)
from src.logging import get_structured_logger


class PostgresReconciliationExecutor:
    """Run reconciliation through one atomic, set-based PostgreSQL query."""

    def __init__(self, result_repo: Any, logger: Any | None = None) -> None:
        self._result_repo = result_repo
        self._logger = logger or get_structured_logger()

    @staticmethod
    def _partner_key_expression(alias: str = "p") -> str:
        """The one canonical-key expression shared by matching and scoped deletes."""
        return (
            f"COALESCE(NULLIF(BTRIM({alias}.partner_trace), ''), "
            f"NULLIF(BTRIM({alias}.partner_metadata->>'vspTransId'), ''), "
            f"NULLIF(BTRIM({alias}.partner_id), ''))"
        )

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
        timestamp_policy: ReconciliationPolicy | None = None,
        started_at: float | None = None,
    ) -> list[ReconciliationOutput]:
        """Match one business-day scope and snapshot the effective timestamp policy."""
        from sqlalchemy import and_, select, text
        from sqlalchemy.ext.asyncio import AsyncSession

        from src.infrastructure.persistence.postgres_schema import (
            ReconciliationResultTable,
        )

        source_file_uuid: UUID | None = None
        if source_file_id:
            try:
                source_file_uuid = UUID(str(source_file_id))
            except (ValueError, TypeError) as exc:
                raise ValueError("source_file_id must be a valid UUID") from exc

        policy = timestamp_policy or ReconciliationPolicy()
        params = {
            "partner": partner,
            "date_str": date_str,
            "start_of_day": start_of_day.replace(tzinfo=None),
            "end_of_day": end_of_day.replace(tzinfo=None),
            "reconciliation_run_id": reconciliation_run_id,
            "source_file_id": source_file_id,
            "source_file_id_uuid": source_file_uuid,
            "scope_type": scope_type.value,
            "mapping_version": mapping_version,
            "timestamp_tolerance_seconds": policy.timestamp_tolerance_seconds,
            "timestamp_timezone": policy.timestamp_timezone,
            "advisory_key": f"{partner}:{date_str}",
        }

        match_insert_sql = f"""
        INSERT INTO reconciliation_result (
            id, partner, date, partner_txn_id, internal_txn_id,
            partner_amount, internal_amount, partner_status, internal_status,
            reconciliation_status, reconciliation_run_id, source_file_id,
            scope_type, mapping_version, partner_record_id, internal_record_id,
            reconciliation_key, partner_trans_date, internal_transaction_time,
            timestamp_status, timestamp_delta_seconds, timestamp_tolerance_seconds,
            timestamp_timezone, timestamp_basis, ambiguous_partner_record_ids,
            ambiguous_internal_record_ids, created_at
        )
        WITH partner_raw AS (
            SELECT p.*,
                {self._partner_key_expression('p')} AS reconciliation_key,
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
        internal_raw AS (
            SELECT i.*,
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
                      SELECT reconciliation_key FROM partner_raw
                  )
              )
        ),
        internal_eligible AS (
            SELECT * FROM internal_raw
            WHERE normalized_status IN ('SUCCESS', 'FAILED', 'REVERSED')
        ),
        partner_groups AS (
            SELECT reconciliation_key,
                COUNT(*)::int AS row_count,
                ARRAY_AGG(CAST(id AS VARCHAR) ORDER BY id) AS record_ids,
                MIN(timestamp_basis) AS timestamp_basis
            FROM partner_raw
            WHERE reconciliation_key IS NOT NULL
            GROUP BY reconciliation_key
        ),
        internal_groups AS (
            SELECT reconciliation_key,
                COUNT(*)::int AS row_count,
                ARRAY_AGG(CAST(id AS VARCHAR) ORDER BY id) AS record_ids
            FROM internal_eligible
            WHERE reconciliation_key IS NOT NULL
            GROUP BY reconciliation_key
        ),
        key_space AS (
            SELECT reconciliation_key FROM partner_groups
            UNION
            SELECT reconciliation_key FROM internal_groups
        ),
        ambiguous_rows AS (
            SELECT
                k.reconciliation_key,
                k.reconciliation_key AS partner_txn_id,
                NULL::VARCHAR AS internal_txn_id,
                NULL::NUMERIC AS partner_amount,
                NULL::NUMERIC AS internal_amount,
                NULL::VARCHAR AS partner_status,
                NULL::VARCHAR AS internal_status,
                'AMBIGUOUS_KEY' AS reconciliation_status,
                NULL::VARCHAR AS partner_record_id,
                NULL::VARCHAR AS internal_record_id,
                NULL::TIMESTAMP AS partner_trans_date,
                NULL::TIMESTAMP AS internal_transaction_time,
                'NOT_EVALUATED' AS timestamp_status,
                NULL::NUMERIC AS timestamp_delta_seconds,
                COALESCE(pg.timestamp_basis, 'LEGACY_STORED') AS timestamp_basis,
                COALESCE(pg.record_ids, ARRAY[]::VARCHAR[]) AS ambiguous_partner_record_ids,
                COALESCE(ig.record_ids, ARRAY[]::VARCHAR[]) AS ambiguous_internal_record_ids,
                COALESCE(pg.row_count, 0) > 0 AS has_partner_source
            FROM key_space k
            LEFT JOIN partner_groups pg ON pg.reconciliation_key = k.reconciliation_key
            LEFT JOIN internal_groups ig ON ig.reconciliation_key = k.reconciliation_key
            WHERE COALESCE(pg.row_count, 0) > 1
               OR COALESCE(ig.row_count, 0) > 1
        ),
        one_to_one_rows AS (
            SELECT
                k.reconciliation_key,
                COALESCE(p.reconciliation_key, p.partner_id, i.partner_txn_id, i.id) AS partner_txn_id,
                CAST(i.id AS VARCHAR) AS internal_txn_id,
                p.partner_amount,
                i.amount AS internal_amount,
                p.partner_status,
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
                CAST(p.id AS VARCHAR) AS partner_record_id,
                CAST(i.id AS VARCHAR) AS internal_record_id,
                p.partner_trans_date,
                i.transaction_time AS internal_transaction_time,
                CASE
                    WHEN p.id IS NULL OR i.id IS NULL THEN 'NOT_EVALUATED'
                    WHEN p.partner_trans_date IS NULL OR i.transaction_time IS NULL THEN 'NOT_AVAILABLE'
                    WHEN ABS(EXTRACT(EPOCH FROM (p.partner_trans_date - i.transaction_time)))
                         <= CAST(:timestamp_tolerance_seconds AS NUMERIC) THEN 'MATCHED'
                    ELSE 'MISMATCH'
                END AS timestamp_status,
                CASE
                    WHEN p.id IS NOT NULL AND i.id IS NOT NULL
                         AND p.partner_trans_date IS NOT NULL AND i.transaction_time IS NOT NULL
                    THEN ROUND(ABS(EXTRACT(EPOCH FROM (p.partner_trans_date - i.transaction_time))), 6)
                    ELSE NULL
                END AS timestamp_delta_seconds,
                COALESCE(p.timestamp_basis, 'LEGACY_STORED') AS timestamp_basis,
                ARRAY[]::VARCHAR[] AS ambiguous_partner_record_ids,
                ARRAY[]::VARCHAR[] AS ambiguous_internal_record_ids,
                p.source_file_id IS NOT NULL AS has_partner_source
            FROM key_space k
            LEFT JOIN partner_groups pg ON pg.reconciliation_key = k.reconciliation_key
            LEFT JOIN internal_groups ig ON ig.reconciliation_key = k.reconciliation_key
            LEFT JOIN partner_raw p
              ON p.reconciliation_key = k.reconciliation_key
             AND COALESCE(pg.row_count, 0) = 1
            LEFT JOIN internal_eligible i
              ON i.reconciliation_key = k.reconciliation_key
             AND COALESCE(ig.row_count, 0) = 1
            WHERE COALESCE(pg.row_count, 0) <= 1
              AND COALESCE(ig.row_count, 0) <= 1
        ),
        unmapped_rows AS (
            SELECT
                NULL::VARCHAR AS reconciliation_key,
                COALESCE(NULLIF(BTRIM(p.partner_id), ''), CAST(p.id AS VARCHAR)) AS partner_txn_id,
                NULL::VARCHAR AS internal_txn_id,
                p.partner_amount,
                NULL::NUMERIC AS internal_amount,
                p.partner_status,
                NULL::VARCHAR AS internal_status,
                'UNMAPPED_SKIPPED' AS reconciliation_status,
                CAST(p.id AS VARCHAR) AS partner_record_id,
                NULL::VARCHAR AS internal_record_id,
                p.partner_trans_date,
                NULL::TIMESTAMP AS internal_transaction_time,
                'NOT_EVALUATED' AS timestamp_status,
                NULL::NUMERIC AS timestamp_delta_seconds,
                COALESCE(p.timestamp_basis, 'LEGACY_STORED') AS timestamp_basis,
                ARRAY[CAST(p.id AS VARCHAR)] AS ambiguous_partner_record_ids,
                ARRAY[]::VARCHAR[] AS ambiguous_internal_record_ids,
                TRUE AS has_partner_source
            FROM partner_raw p
            WHERE p.reconciliation_key IS NULL
            UNION ALL
            SELECT
                NULL::VARCHAR AS reconciliation_key,
                COALESCE(NULLIF(BTRIM(i.partner_txn_id), ''), i.id) AS partner_txn_id,
                CAST(i.id AS VARCHAR) AS internal_txn_id,
                NULL::NUMERIC AS partner_amount,
                i.amount AS internal_amount,
                NULL::VARCHAR AS partner_status,
                i.status AS internal_status,
                'UNMAPPED_SKIPPED' AS reconciliation_status,
                NULL::VARCHAR AS partner_record_id,
                CAST(i.id AS VARCHAR) AS internal_record_id,
                NULL::TIMESTAMP AS partner_trans_date,
                i.transaction_time AS internal_transaction_time,
                'NOT_EVALUATED' AS timestamp_status,
                NULL::NUMERIC AS timestamp_delta_seconds,
                'LEGACY_STORED' AS timestamp_basis,
                ARRAY[]::VARCHAR[] AS ambiguous_partner_record_ids,
                ARRAY[CAST(i.id AS VARCHAR)] AS ambiguous_internal_record_ids,
                FALSE AS has_partner_source
            FROM internal_eligible i
            WHERE i.reconciliation_key IS NULL
        ),
        evidence_rows AS (
            SELECT * FROM ambiguous_rows
            UNION ALL
            SELECT * FROM one_to_one_rows
            UNION ALL
            SELECT * FROM unmapped_rows
        )
        SELECT
            CAST(gen_random_uuid() AS VARCHAR), :partner, :date_str,
            partner_txn_id, internal_txn_id, partner_amount, internal_amount,
            partner_status, internal_status, reconciliation_status,
            CAST(:reconciliation_run_id AS VARCHAR),
            CASE WHEN has_partner_source THEN COALESCE(
                (SELECT CAST(source_file_id AS VARCHAR) FROM partner_raw p
                 WHERE p.id::VARCHAR = partner_record_id LIMIT 1),
                CAST(:source_file_id AS VARCHAR)
            ) ELSE CAST(:source_file_id AS VARCHAR) END,
            CAST(:scope_type AS VARCHAR), CAST(:mapping_version AS VARCHAR),
            partner_record_id, internal_record_id, reconciliation_key,
            partner_trans_date, internal_transaction_time, timestamp_status,
            timestamp_delta_seconds, CAST(:timestamp_tolerance_seconds AS NUMERIC),
            :timestamp_timezone, timestamp_basis, ambiguous_partner_record_ids,
            ambiguous_internal_record_ids, NOW()
        FROM evidence_rows
        """

        delete_sql = self._delete_sql(source_file_id, scope_type)
        excluded_internal_sql = """
        SELECT COUNT(*)
        FROM internal_transaction i
        WHERE i.partner = :partner
          AND i.transaction_time >= :start_of_day
          AND i.transaction_time <= :end_of_day
          AND LOWER(BTRIM(i.status)) NOT IN (
              'success', 'thành công', 'matched',
              'fail', 'failed', 'thất bại',
              'reversed', 'hoàn tiền'
          )
          AND (
              CAST(:source_file_id_uuid AS UUID) IS NULL
              OR CAST(:scope_type AS VARCHAR) = 'FULL_SNAPSHOT'
              OR NULLIF(BTRIM(i.partner_txn_id), '') IN (
                  SELECT {key_expression}
                  FROM partner_transaction p
                  WHERE p.identify = :partner
                    AND p.reconciliation_date >= :start_of_day
                    AND p.reconciliation_date <= :end_of_day
                    AND p.source_file_id = CAST(:source_file_id_uuid AS UUID)
              )
          )
        """.format(key_expression=self._partner_key_expression("p"))
        async with self._result_repo.engine.begin() as conn:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:advisory_key, 0))"),
                params,
            )
            await conn.execute(text(delete_sql), params)
            await conn.execute(text(match_insert_sql), params)
            excluded_internal_count = int(
                (await conn.execute(text(excluded_internal_sql), params)).scalar() or 0
            )

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
            results: list[ReconciliationOutput] = [
                row_to_reconciliation_result(row) for row in rows
            ]

        metrics = Counter(item.timestamp_status.value for item in results)
        metrics["ambiguousKey"] = sum(
            item.reconciliation_status.value == "AMBIGUOUS_KEY" for item in results
        )
        metrics["unmappedSkipped"] = sum(
            item.reconciliation_status.value == "UNMAPPED_SKIPPED" for item in results
        )
        duration_ms = self._duration_ms(started_at)
        self._logger.get_logger().info(
            "reconciliation_completed (SQL mode)",
            extra={
                "event": "RECONCILIATION_COMPLETED",
                "partner": partner,
                "total_processed": len(results),
                "duration_ms": round(duration_ms, 2),
                "timestamp_matched": metrics["MATCHED"],
                "timestamp_mismatch": metrics["MISMATCH"],
                "timestamp_not_available": metrics["NOT_AVAILABLE"],
                "timestamp_not_evaluated": metrics["NOT_EVALUATED"],
                "ambiguous_key": metrics["ambiguousKey"],
                "unmapped_key": metrics["unmappedSkipped"],
                "excluded_internal_pending_unknown": excluded_internal_count,
            },
        )
        return results

    @staticmethod
    def _duration_ms(started_at: float | None) -> float:
        return (time.perf_counter() - started_at) * 1000 if started_at else 0.0

    @classmethod
    def _delete_sql(
        cls,
        source_file_id: str | None,
        scope_type: ReconciliationScopeType,
    ) -> str:
        key_expression = cls._partner_key_expression("partner_transaction")
        if source_file_id and scope_type in {
            ReconciliationScopeType.INCREMENTAL_APPEND,
            ReconciliationScopeType.REPLACEMENT,
        }:
            return f"""
            DELETE FROM reconciliation_result
            WHERE partner = :partner AND date = :date_str
              AND (source_file_id = :source_file_id OR partner_txn_id IN (
                  SELECT {key_expression}
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
