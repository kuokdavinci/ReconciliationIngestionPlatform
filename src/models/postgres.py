import asyncio
from datetime import datetime, timezone
from sqlalchemy import Column, String, Numeric, DateTime, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class PartnerTransactionTable(Base):
    __tablename__ = "partner_transaction"
    __table_args__ = (
        UniqueConstraint(
            "identify",
            "ingestion_key",
            name="uq_partner_transaction_identify_ingestion_key",
        ),
    )

    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    request_id = Column(PG_UUID(as_uuid=True), nullable=False)
    identify = Column(String(255), nullable=False, index=True)
    workflow_type = Column(String(255), nullable=False)
    reconciliation_date = Column(DateTime, nullable=False, index=True)
    operation_status = Column(String(50), default="IN_PROGRESS")
    reconciliation_status = Column(String(50), default="")
    connector_data = Column(Text, default="")
    extra_data = Column(Text, default="")
    source_file_id = Column(PG_UUID(as_uuid=True), nullable=False, index=True)
    ingestion_key = Column(String(255), nullable=False, index=True)
    
    # Nested PartnerData fields flattened for queries/indices
    partner_id = Column(String(255), nullable=False)
    partner_trace = Column(String(255), nullable=True, index=True)
    partner_status = Column(String(255), nullable=False)
    partner_amount = Column(Numeric(20, 4), nullable=False)
    partner_currency = Column(String(50), nullable=False)
    partner_trans_date = Column(DateTime, nullable=True)
    
    # Extra dynamic columns
    partner_metadata = Column(JSONB, default=dict)
    
    created_by = Column(String(255), default="system")
    created_date = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_modified_by = Column(String(255), default="system")
    last_modified_date = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class InternalTransactionTable(Base):
    __tablename__ = "internal_transaction"

    id = Column(String(255), primary_key=True)
    partner = Column(String(255), nullable=False, index=True)
    partner_txn_id = Column(String(255), nullable=False, index=True)
    amount = Column(Numeric(20, 4), nullable=False)
    currency = Column(String(50), default="VND")
    status = Column(String(50), nullable=False)
    transaction_time = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class ReconciliationResultTable(Base):
    __tablename__ = "reconciliation_result"

    id = Column(String(255), primary_key=True)
    partner = Column(String(255), nullable=False, index=True)
    date = Column(String(10), nullable=False, index=True)
    partner_txn_id = Column(String(255), nullable=False)
    internal_txn_id = Column(String(255), nullable=True)
    
    partner_amount = Column(Numeric(20, 4), nullable=True)
    internal_amount = Column(Numeric(20, 4), nullable=True)
    
    partner_status = Column(String(50), nullable=True)
    internal_status = Column(String(50), nullable=True)
    
    reconciliation_status = Column(String(50), nullable=False, index=True)
    reconciliation_run_id = Column(String(255), nullable=True, index=True)
    source_file_id = Column(String(255), nullable=True, index=True)
    scope_type = Column(String(50), nullable=True)
    mapping_version = Column(String(50), nullable=True)
    
    partner_record_id = Column(String(255), nullable=True)
    internal_record_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


_pg_engine = None
_pg_engine_loop = None
_pg_engine_url = None

def get_pg_engine():
    global _pg_engine, _pg_engine_loop, _pg_engine_url
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    from src.config.settings import settings
    postgres_url = settings.postgres_url
    if postgres_url.startswith("postgresql://"):
        postgres_url = postgres_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    if (
        _pg_engine is None
        or (current_loop is not None and _pg_engine_loop is not current_loop)
        or _pg_engine_url != postgres_url
    ):
        _pg_engine = create_async_engine(postgres_url, echo=False)
        _pg_engine_loop = current_loop
        _pg_engine_url = postgres_url
    return _pg_engine

def set_pg_engine(engine):
    global _pg_engine, _pg_engine_loop, _pg_engine_url
    _pg_engine = engine
    try:
        _pg_engine_loop = asyncio.get_running_loop()
    except RuntimeError:
        _pg_engine_loop = None
    _pg_engine_url = str(engine.url) if engine is not None else None

async def init_postgres_db(postgres_url: str, use_unlogged: bool = False):
    """Apply pending Alembic migrations or create tables if fresh DB.

    Args:
        postgres_url: PostgreSQL connection URL.
        use_unlogged: If True, set partner_transaction and
            internal_transaction to UNLOGGED for performance.
            Defaults to False (full durability).
    """
    # Ensure correct scheme for asyncpg
    if postgres_url.startswith("postgresql://"):
        postgres_url = postgres_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(postgres_url, echo=False)

    # Check if partner_transaction table already exists.
    from sqlalchemy import text
    async with engine.connect() as conn:
        has_partner = await conn.execute(
            text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'partner_transaction')")
        )
        partner_exists = has_partner.scalar()

    if partner_exists:
        # Tables exist (from old create_all or previous run) — stamp head
        async with engine.begin() as conn:
            try:
                await conn.run_sync(_stamp_head)
            except Exception:
                pass
            if use_unlogged:
                await conn.execute(text("ALTER TABLE partner_transaction SET UNLOGGED;"))
                await conn.execute(text("ALTER TABLE internal_transaction SET UNLOGGED;"))
    else:
        # Fresh database — create tables via SQLAlchemy first, then stamp head
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            try:
                await conn.run_sync(_stamp_head)
            except Exception:
                pass
            if use_unlogged:
                await conn.execute(text("ALTER TABLE partner_transaction SET UNLOGGED;"))
                await conn.execute(text("ALTER TABLE internal_transaction SET UNLOGGED;"))
    await engine.dispose()


def _stamp_head(connection):
    """Stamp the database with the current Alembic head revision."""
    from alembic import command

    cfg = _alembic_config(connection)
    cfg.attributes["connection"] = connection
    command.stamp(cfg, "head")


def _run_alembic_upgrade(connection):
    """Run Alembic migrations to head on an existing SQLAlchemy connection.

    This is called via conn.run_sync() from inside an async context,
    so it receives a synchronous connection. We pass it through to
    Alembic via config.attributes so env.py can use it directly
    without creating its own engine or calling asyncio.run().
    """
    from alembic import command

    cfg = _alembic_config(connection)
    cfg.attributes["connection"] = connection
    command.upgrade(cfg, "head")


def _alembic_config(connection):
    """Load Alembic config from the application root, independent of cwd."""
    from pathlib import Path
    from alembic.config import Config

    config_path = Path(__file__).resolve().parents[2] / "alembic.ini"
    cfg = Config(str(config_path))
    cfg.set_main_option("sqlalchemy.url", str(connection.engine.url))
    return cfg
