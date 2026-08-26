"""PostgreSQL repository for canonical partner transactions."""

from datetime import datetime
import json
import logging
import time
from typing import Any, Optional
from uuid import UUID

from src.domain.ingestion.quality import QualityRuleCode
from src.domain.partner_transaction.duplicates import (
    BatchWriteResult,
    DuplicateDetail,
    fingerprint_payload,
)
from src.domain.partner_transaction.models import (
    DataContainer,
    FastDataContainer,
)
from src.infrastructure.partner_transaction.mappers import (
    data_container_to_row,
    document_to_data_container,
    row_to_data_container,
)
from src.infrastructure.persistence.time import as_utc_naive


logger = logging.getLogger(__name__)


_PARTNER_TRANSACTION_COLUMNS = (
    "id",
    "request_id",
    "identify",
    "workflow_type",
    "reconciliation_date",
    "operation_status",
    "reconciliation_status",
    "connector_data",
    "extra_data",
    "source_file_id",
    "ingestion_key",
    "partner_id",
    "partner_trace",
    "partner_status",
    "partner_amount",
    "partner_currency",
    "partner_trans_date",
    "partner_metadata",
    "created_by",
    "created_date",
    "last_modified_by",
    "last_modified_date",
)

_PARTNER_TRANSACTION_COLUMN_SQL = ", ".join(_PARTNER_TRANSACTION_COLUMNS)
_STAGE_COLUMNS = ("incoming_ordinal", *_PARTNER_TRANSACTION_COLUMNS)
_FINGERPRINT_COLUMNS = (
    "identify",
    "ingestion_key",
    "partner_id",
    "partner_trace",
    "partner_status",
    "partner_amount",
    "partner_currency",
    "partner_trans_date",
    "partner_metadata",
)
_CONFLICT_KEY_TABLE = "partner_transaction_conflict_keys"
_CONFLICT_KEY_COLUMNS = ("identify", "ingestion_key")


def _row_to_copy_tuple(row: dict, incoming_ordinal: int) -> tuple:
    return (
        incoming_ordinal,
        *(row[column] for column in _PARTNER_TRANSACTION_COLUMNS[:16]),
        row["partner_trans_date"],
        json.dumps(row["partner_metadata"])
        if isinstance(row["partner_metadata"], (dict, list))
        else row["partner_metadata"],
        *(row[column] for column in _PARTNER_TRANSACTION_COLUMNS[18:]),
    )


class DataContainerRepository:
    """PostgreSQL repository for canonical partner transactions."""

    def __init__(self, db: Any = None, engine: Any = None):
        del db  # Retained in the signature for existing dependency wiring.
        if engine is None:
            from src.infrastructure.persistence.postgres_connection import get_pg_engine

            engine = get_pg_engine()
        self.engine = engine

    async def copy_records(self, docs: list[DataContainer]) -> int:
        """Compatibility wrapper that preserves conflict-safe insertion."""
        if not docs:
            return 0
        rows = [data_container_to_row(doc) for doc in docs]
        inserted, _conflicts = await self._insert_rows_conflict_safe(rows)
        return inserted

    async def _insert_rows_conflict_safe(
        self,
        rows: list[dict],
        *,
        timings_ms: dict[str, float] | None = None,
    ) -> tuple[int, dict[tuple[str, str], int]]:
        """Atomically insert rows and return inserted-count per conflict key."""
        tuples = [
            _row_to_copy_tuple(row, incoming_ordinal) for incoming_ordinal, row in enumerate(rows)
        ]
        stage_table = "partner_transaction_stage"
        create_stage_sql = (
            f"CREATE TEMP TABLE {stage_table} "
            "(incoming_ordinal bigint NOT NULL, "
            "LIKE partner_transaction INCLUDING DEFAULTS) ON COMMIT DROP"
        )
        classify_sql = f"""
            WITH incoming_counts AS (
                SELECT identify, ingestion_key, COUNT(*)::bigint AS incoming_count
                FROM {stage_table}
                GROUP BY identify, ingestion_key
            ),
            inserted AS (
                INSERT INTO partner_transaction ({_PARTNER_TRANSACTION_COLUMN_SQL})
                SELECT {_PARTNER_TRANSACTION_COLUMN_SQL}
                FROM {stage_table}
                ORDER BY incoming_ordinal
                ON CONFLICT (identify, ingestion_key) DO NOTHING
                RETURNING identify, ingestion_key
            ),
            classified AS (
                SELECT
                    incoming.identify,
                    incoming.ingestion_key,
                    CASE WHEN inserted.ingestion_key IS NULL THEN 0 ELSE 1 END
                        AS inserted_for_key,
                    incoming.incoming_count
                        - CASE WHEN inserted.ingestion_key IS NULL THEN 0 ELSE 1 END
                        AS duplicate_count
                FROM incoming_counts AS incoming
                LEFT JOIN inserted
                  ON inserted.identify = incoming.identify
                 AND inserted.ingestion_key = incoming.ingestion_key
            ),
            summary AS (
                SELECT COUNT(*)::bigint AS inserted_count FROM inserted
            )
            SELECT
                classified.identify,
                classified.ingestion_key,
                classified.inserted_for_key,
                classified.duplicate_count,
                summary.inserted_count
            FROM classified
            CROSS JOIN summary
            WHERE classified.duplicate_count > 0
            UNION ALL
            SELECT
                NULL::text AS identify,
                NULL::text AS ingestion_key,
                0::bigint AS inserted_for_key,
                0::bigint AS duplicate_count,
                summary.inserted_count
            FROM summary
            WHERE NOT EXISTS (
                SELECT 1 FROM classified WHERE classified.duplicate_count > 0
            )
        """

        stage_started = time.perf_counter()
        async with self.engine.begin() as conn:
            # Start the SQLAlchemy-managed transaction before using the raw
            # asyncpg connection. Otherwise PostgreSQL may auto-commit the
            # CREATE TEMP TABLE and immediately apply ON COMMIT DROP.
            from sqlalchemy import text

            await conn.execute(text(create_stage_sql))
            if timings_ms is not None:
                timings_ms["stage_setup_ms"] = (time.perf_counter() - stage_started) * 1000

            copy_started = time.perf_counter()
            raw_conn = await conn.get_raw_connection()
            asyncpg_conn = raw_conn.driver_connection
            await asyncpg_conn.copy_records_to_table(
                stage_table,
                columns=_STAGE_COLUMNS,
                records=tuples,
            )
            if timings_ms is not None:
                timings_ms["copy_ms"] = (time.perf_counter() - copy_started) * 1000

            insert_started = time.perf_counter()
            classified_rows = await asyncpg_conn.fetch(classify_sql)
            if timings_ms is not None:
                timings_ms["insert_ms"] = (time.perf_counter() - insert_started) * 1000

        inserted = int(classified_rows[0]["inserted_count"]) if classified_rows else 0
        conflict_insert_counts = {
            (str(row["identify"]), str(row["ingestion_key"])): int(row["inserted_for_key"])
            for row in classified_rows
            if row["identify"] is not None
        }
        return inserted, conflict_insert_counts

    async def _find_existing_for_keys(
        self,
        keys: set[tuple[str, str]],
    ) -> dict[tuple[str, str], dict[str, Any]]:
        """Fetch all conflict payloads through a bounded set-based join.

        A composite ``IN`` expression expands into one SQL expression and two
        bind parameters per key. PostgreSQL hits its expression stack limit at
        duplicate-heavy batch sizes before the query can execute. A temporary
        key table keeps the lookup set-based while allowing PostgreSQL to plan
        a normal indexed join.
        """

        if not keys:
            return {}

        from sqlalchemy import text

        create_key_table_sql = f"""
            CREATE TEMP TABLE {_CONFLICT_KEY_TABLE} (
                identify text NOT NULL,
                ingestion_key text NOT NULL,
                PRIMARY KEY (identify, ingestion_key)
            ) ON COMMIT DROP
        """
        fingerprint_columns_sql = ", ".join(
            f"p.{column} AS {column}" for column in _FINGERPRINT_COLUMNS
        )
        lookup_sql = f"""
            SELECT {fingerprint_columns_sql}
            FROM partner_transaction AS p
            JOIN {_CONFLICT_KEY_TABLE} AS k
              ON k.identify = p.identify
             AND k.ingestion_key = p.ingestion_key
        """

        async with self.engine.begin() as conn:
            await conn.execute(text(create_key_table_sql))
            raw_conn = await conn.get_raw_connection()
            asyncpg_conn = raw_conn.driver_connection
            await asyncpg_conn.copy_records_to_table(
                _CONFLICT_KEY_TABLE,
                columns=_CONFLICT_KEY_COLUMNS,
                records=sorted(keys),
            )
            result = await conn.execute(text(lookup_sql))
            records = result.mappings().all()
        return {
            (str(record["identify"]), str(record["ingestion_key"])): dict(record)
            for record in records
        }

    async def insert_many(
        self,
        docs: list[DataContainer | FastDataContainer | dict],
        ordered: bool = True,
    ) -> BatchWriteResult:
        started = time.perf_counter()
        del ordered  # The PostgreSQL adapter always uses one set-based write.
        if not docs:
            return BatchWriteResult(inserted=0)

        mapping_started = time.perf_counter()
        rows = [
            data_container_to_row(document_to_data_container(doc) if isinstance(doc, dict) else doc)
            for doc in docs
        ]
        timings_ms: dict[str, float] = {
            "row_mapping_ms": (time.perf_counter() - mapping_started) * 1000,
        }
        inserted, conflict_insert_counts = await self._insert_rows_conflict_safe(
            rows,
            timings_ms=timings_ms,
        )
        conflict_keys = set(conflict_insert_counts)
        if not conflict_keys:
            self._log_batch_write_metrics(
                input_rows=len(rows),
                inserted=inserted,
                duplicates=0,
                equivalent_duplicates=0,
                conflicting_duplicates=0,
                conflict_keys=0,
                timings_ms=timings_ms,
                started=started,
            )
            return BatchWriteResult(inserted=inserted)

        incoming_by_key: dict[
            tuple[str, str],
            list[tuple[int, dict[str, Any]]],
        ] = {}
        for incoming_index, row in enumerate(rows):
            key = (str(row["identify"]), str(row["ingestion_key"]))
            if key in conflict_keys:
                incoming_by_key.setdefault(key, []).append((incoming_index, row))

        lookup_started = time.perf_counter()
        existing = await self._find_existing_for_keys(conflict_keys)
        timings_ms["conflict_lookup_ms"] = (time.perf_counter() - lookup_started) * 1000

        duplicate_details: list[DuplicateDetail] = []
        equivalent = 0
        conflicting = 0
        fingerprint_started = time.perf_counter()
        for key in sorted(conflict_keys):
            incoming = incoming_by_key.get(key, [])
            existing_row = existing.get(key)
            if existing_row is None:
                continue
            existing_fingerprint = fingerprint_payload(existing_row)
            duplicate_start = conflict_insert_counts[key]
            for incoming_index, row in incoming[duplicate_start:]:
                incoming_fingerprint = fingerprint_payload(row)
                is_equivalent = incoming_fingerprint == existing_fingerprint
                duplicate_type = (
                    QualityRuleCode.EQUIVALENT_DUPLICATE
                    if is_equivalent
                    else QualityRuleCode.CONFLICTING_DUPLICATE
                )
                if is_equivalent:
                    equivalent += 1
                else:
                    conflicting += 1
                duplicate_details.append(
                    DuplicateDetail(
                        identify=str(row["identify"]),
                        ingestion_key=str(row["ingestion_key"]),
                        duplicate_type=duplicate_type,
                        incoming_index=incoming_index,
                        incoming_fingerprint=incoming_fingerprint,
                        existing_fingerprint=existing_fingerprint,
                        partner_id=(
                            str(row["partner_id"]) if row["partner_id"] is not None else None
                        ),
                        partner_trace=row["partner_trace"],
                    )
                )
        timings_ms["fingerprint_ms"] = (time.perf_counter() - fingerprint_started) * 1000

        duplicates = max(len(rows) - inserted, 0)
        self._log_batch_write_metrics(
            input_rows=len(rows),
            inserted=inserted,
            duplicates=duplicates,
            equivalent_duplicates=equivalent,
            conflicting_duplicates=conflicting,
            conflict_keys=len(conflict_keys),
            timings_ms=timings_ms,
            started=started,
        )
        return BatchWriteResult(
            inserted=inserted,
            duplicates=duplicates,
            equivalent_duplicates=equivalent,
            conflicting_duplicates=conflicting,
            duplicate_details=duplicate_details,
        )

    @staticmethod
    def _log_batch_write_metrics(
        *,
        input_rows: int,
        inserted: int,
        duplicates: int,
        equivalent_duplicates: int,
        conflicting_duplicates: int,
        conflict_keys: int,
        timings_ms: dict[str, float],
        started: float,
    ) -> None:
        """Emit bounded phase metrics without adding timing fields to the result contract."""
        timings_ms.setdefault("stage_setup_ms", 0.0)
        timings_ms.setdefault("copy_ms", 0.0)
        timings_ms.setdefault("insert_ms", 0.0)
        timings_ms.setdefault("conflict_lookup_ms", 0.0)
        timings_ms.setdefault("fingerprint_ms", 0.0)
        total_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "PERF_PARTNER_TRANSACTION_BATCH: "
            "input_rows=%d inserted_rows=%d duplicate_rows=%d "
            "equivalent_duplicate_rows=%d conflicting_duplicate_rows=%d "
            "conflict_keys=%d row_mapping_ms=%.2f stage_setup_ms=%.2f "
            "copy_ms=%.2f insert_ms=%.2f conflict_lookup_ms=%.2f "
            "fingerprint_ms=%.2f total_ms=%.2f",
            input_rows,
            inserted,
            duplicates,
            equivalent_duplicates,
            conflicting_duplicates,
            conflict_keys,
            timings_ms["row_mapping_ms"],
            timings_ms["stage_setup_ms"],
            timings_ms["copy_ms"],
            timings_ms["insert_ms"],
            timings_ms["conflict_lookup_ms"],
            timings_ms["fingerprint_ms"],
            total_ms,
        )

    async def find_by_trace(self, identify: str, trace: str) -> Optional[DataContainer]:
        from sqlalchemy import select, and_
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable

        async with AsyncSession(self.engine) as session:
            stmt = select(PartnerTransactionTable).where(
                and_(
                    PartnerTransactionTable.identify == identify,
                    PartnerTransactionTable.partner_trace == trace,
                )
            )
            result = await session.execute(stmt)
            row = result.scalars().first()
            return row_to_data_container(row) if row else None

    async def find_by_ingestion_key(
        self,
        identify: str,
        ingestion_key: str,
    ) -> Optional[DataContainer]:
        from sqlalchemy import and_, select
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable

        async with AsyncSession(self.engine) as session:
            stmt = select(PartnerTransactionTable).where(
                and_(
                    PartnerTransactionTable.identify == identify,
                    PartnerTransactionTable.ingestion_key == ingestion_key,
                )
            )
            result = await session.execute(stmt)
            row = result.scalars().first()
            return row_to_data_container(row) if row else None

    async def find_existing_fingerprint(self, record: Any) -> str | None:
        """Return the current fingerprint for an operator accept-existing check."""
        identify = getattr(record, "partner", None)
        ingestion_key = getattr(record, "ingestion_key", None)
        if not identify or not ingestion_key:
            return None
        existing = await self.find_by_ingestion_key(str(identify), str(ingestion_key))
        if existing is None:
            return None
        if isinstance(existing, dict):
            existing = document_to_data_container(existing)
        return fingerprint_payload(data_container_to_row(existing))

    async def find_by_source_file(self, source_file_id: UUID) -> list[DataContainer]:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable

        async with AsyncSession(self.engine) as session:
            stmt = select(PartnerTransactionTable).where(
                PartnerTransactionTable.source_file_id == source_file_id
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [row_to_data_container(r) for r in rows]

    async def find_by_date_range(
        self, identify: str, start: datetime, end: datetime
    ) -> list[DataContainer]:
        start = as_utc_naive(start)
        end = as_utc_naive(end)

        from sqlalchemy import select, and_
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable

        async with AsyncSession(self.engine) as session:
            stmt = select(PartnerTransactionTable).where(
                and_(
                    PartnerTransactionTable.identify == identify,
                    PartnerTransactionTable.reconciliation_date >= start,
                    PartnerTransactionTable.reconciliation_date <= end,
                )
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [row_to_data_container(r) for r in rows]

    async def find_reconciliation_keys_by_date_range(
        self,
        identify: str,
        start: datetime,
        end: datetime,
        *,
        exclude_source_file_id: UUID | None = None,
    ) -> set[str]:
        """Return the business keys used by reconciliation for a date range.

        Scope analysis only needs a compact key projection, not full partner
        transaction documents.  Keeping this query in the PostgreSQL adapter
        also ensures that the analysis uses the same key precedence as the
        reconciliation engine: trace, ``vspTransId``, then partner id.
        """
        start = as_utc_naive(start)
        end = as_utc_naive(end)

        from sqlalchemy import and_, select
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable

        conditions = [
            PartnerTransactionTable.identify == identify,
            PartnerTransactionTable.reconciliation_date >= start,
            PartnerTransactionTable.reconciliation_date <= end,
        ]
        if exclude_source_file_id is not None:
            conditions.append(PartnerTransactionTable.source_file_id != exclude_source_file_id)

        async with AsyncSession(self.engine) as session:
            stmt = select(
                PartnerTransactionTable.partner_id,
                PartnerTransactionTable.partner_trace,
                PartnerTransactionTable.partner_metadata,
            ).where(and_(*conditions))
            result = await session.execute(stmt)

        from src.reconciliation.keys import normalize_reconciliation_key

        keys: set[str] = set()
        for partner_id, partner_trace, metadata in result.all():
            vsp_trans_id = metadata.get("vspTransId") if isinstance(metadata, dict) else None
            key = normalize_reconciliation_key(partner_trace, vsp_trans_id, partner_id)
            if key:
                keys.add(key)
        return keys

    async def find_by_duplicate_key(
        self, identify: str, reconciliation_date: datetime, trace: str
    ) -> Optional[DataContainer]:
        reconciliation_date = as_utc_naive(reconciliation_date)

        from sqlalchemy import select, and_
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable

        async with AsyncSession(self.engine) as session:
            stmt = select(PartnerTransactionTable).where(
                and_(
                    PartnerTransactionTable.identify == identify,
                    PartnerTransactionTable.reconciliation_date == reconciliation_date,
                    PartnerTransactionTable.partner_trace == trace,
                )
            )
            result = await session.execute(stmt)
            row = result.scalars().first()
            return row_to_data_container(row) if row else None

    async def find_many(self, query: dict) -> list[DataContainer]:
        from sqlalchemy import select, and_
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable

        conditions = []
        for key, val in query.items():
            if key == "identify":
                conditions.append(PartnerTransactionTable.identify == val)
            elif key in ("reconciliationDate", "reconciliation_date"):
                if isinstance(val, dict):
                    for op, limit_val in val.items():
                        if hasattr(limit_val, "tzinfo") and limit_val.tzinfo is not None:
                            limit_val = as_utc_naive(limit_val)
                        if op == "$gte":
                            conditions.append(
                                PartnerTransactionTable.reconciliation_date >= limit_val
                            )
                        elif op == "$lte":
                            conditions.append(
                                PartnerTransactionTable.reconciliation_date <= limit_val
                            )
                else:
                    if hasattr(val, "tzinfo") and val.tzinfo is not None:
                        val = as_utc_naive(val)
                    conditions.append(PartnerTransactionTable.reconciliation_date == val)
            elif key in ("partnerData.trace", "partner_trace"):
                conditions.append(PartnerTransactionTable.partner_trace == val)
            elif key in ("partnerData.status", "partner_status"):
                conditions.append(PartnerTransactionTable.partner_status == val)
            elif key in ("partnerData.amount", "partner_amount"):
                if isinstance(val, dict):
                    for op, limit_val in val.items():
                        from bson.decimal128 import Decimal128
                        from decimal import Decimal

                        if isinstance(limit_val, Decimal128):
                            limit_val = limit_val.to_decimal()
                        elif not isinstance(limit_val, Decimal):
                            limit_val = Decimal(str(limit_val))

                        if op == "$gte":
                            conditions.append(PartnerTransactionTable.partner_amount >= limit_val)
                        elif op == "$lte":
                            conditions.append(PartnerTransactionTable.partner_amount <= limit_val)
                else:
                    from bson.decimal128 import Decimal128
                    from decimal import Decimal

                    if isinstance(val, Decimal128):
                        val = val.to_decimal()
                    elif not isinstance(val, Decimal):
                        val = Decimal(str(val))
                    conditions.append(PartnerTransactionTable.partner_amount == val)
            elif key in ("sourceFileId", "source_file_id"):
                from uuid import UUID

                if isinstance(val, str):
                    val = UUID(val)
                conditions.append(PartnerTransactionTable.source_file_id == val)

        async with AsyncSession(self.engine) as session:
            stmt = select(PartnerTransactionTable)
            if conditions:
                stmt = stmt.where(and_(*conditions))
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [row_to_data_container(r) for r in rows]

    async def find_by_id(self, transaction_id: UUID | str) -> Optional[DataContainer]:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable

        if isinstance(transaction_id, str):
            try:
                transaction_id = UUID(transaction_id)
            except ValueError:
                return None
        async with AsyncSession(self.engine) as session:
            result = await session.execute(
                select(PartnerTransactionTable).where(PartnerTransactionTable.id == transaction_id)
            )
            row = result.scalars().first()
            return row_to_data_container(row) if row else None

    async def count(self, query: Optional[dict] = None) -> int:
        return len(await self.find_many(query or {}))

    async def count_by_source_file(self, source_file_id: UUID | str) -> int:
        return await self.count({"sourceFileId": source_file_id})

    async def count_by_partner(self, query: Optional[dict] = None) -> dict[str, int]:
        records = await self.find_many(query or {})
        counts: dict[str, int] = {}
        for record in records:
            counts[record.identify] = counts.get(record.identify, 0) + 1
        return counts

    async def delete_by_source_file(self, source_file_id: UUID | str) -> int:
        from sqlalchemy import delete
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable

        if isinstance(source_file_id, str):
            source_file_id = UUID(source_file_id)
        async with self.engine.begin() as conn:
            result = await conn.execute(
                delete(PartnerTransactionTable).where(
                    PartnerTransactionTable.source_file_id == source_file_id
                )
            )
            return int(result.rowcount or 0)

    async def delete_by_partner(self, partner: str) -> int:
        """Delete canonical partner transactions for an isolated test/maintenance scope."""
        from sqlalchemy import delete
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable

        async with self.engine.begin() as conn:
            result = await conn.execute(
                delete(PartnerTransactionTable).where(
                    PartnerTransactionTable.identify == partner,
                )
            )
            return int(result.rowcount or 0)

    async def rebind_source_file_by_ingestion_keys(
        self, identify: str, ingestion_keys: list[str], source_file_id: UUID | str
    ) -> int:
        """Rebind existing canonical rows to the current logical file claim."""
        if not ingestion_keys:
            return 0
        from sqlalchemy import update
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable

        if isinstance(source_file_id, str):
            source_file_id = UUID(source_file_id)
        async with self.engine.begin() as conn:
            result = await conn.execute(
                update(PartnerTransactionTable)
                .where(
                    PartnerTransactionTable.identify == identify,
                    PartnerTransactionTable.ingestion_key.in_(ingestion_keys),
                )
                .values(source_file_id=source_file_id)
            )
            return int(result.rowcount or 0)

    async def rebind_source_file(
        self,
        source_file_id: UUID | str,
        target_source_file_id: UUID | str,
    ) -> int:
        """Move only rows created by one temporary page claim to the batch file."""
        from sqlalchemy import update
        from src.infrastructure.persistence.postgres_schema import PartnerTransactionTable

        if isinstance(source_file_id, str):
            source_file_id = UUID(source_file_id)
        if isinstance(target_source_file_id, str):
            target_source_file_id = UUID(target_source_file_id)
        async with self.engine.begin() as conn:
            result = await conn.execute(
                update(PartnerTransactionTable)
                .where(PartnerTransactionTable.source_file_id == source_file_id)
                .values(source_file_id=target_source_file_id)
            )
            return int(result.rowcount or 0)
