"""Compatibility facade for PostgreSQL schema and connection adapters.

New production code should import schema from
``src.infrastructure.persistence.postgres_schema`` and connection helpers from
``src.infrastructure.persistence.postgres_connection``.
"""

from src.infrastructure.persistence.postgres_connection import (
    _alembic_config,
    get_pg_engine,
    init_postgres_db,
    set_pg_engine,
)
from src.infrastructure.persistence.postgres_schema import (
    Base,
    InternalTransactionTable,
    PartnerTransactionTable,
    ReconciliationResultTable,
)

__all__ = [
    "Base",
    "PartnerTransactionTable",
    "InternalTransactionTable",
    "ReconciliationResultTable",
    "get_pg_engine",
    "set_pg_engine",
    "init_postgres_db",
    "_alembic_config",
]
