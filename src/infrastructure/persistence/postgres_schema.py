"""SQLAlchemy schema for PostgreSQL persistence."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class PartnerTransactionTable(Base):  # type: ignore[misc, valid-type]
    __tablename__ = "partner_transaction"
    __table_args__ = (
        UniqueConstraint(
            "identify",
            "ingestion_key",
            name="uq_partner_transaction_identify_ingestion_key",
        ),
        Index(
            "ix_partner_transaction_identify_reconciliation_date",
            "identify",
            "reconciliation_date",
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
    partner_id = Column(String(255), nullable=False)
    partner_trace = Column(String(255), nullable=True, index=True)
    partner_status = Column(String(255), nullable=False)
    partner_amount = Column(Numeric(20, 4), nullable=False)
    partner_currency = Column(String(50), nullable=False)
    partner_trans_date = Column(DateTime, nullable=True)
    partner_metadata = Column(JSONB, default=dict)
    created_by = Column(String(255), default="system")
    created_date = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_modified_by = Column(String(255), default="system")
    last_modified_date = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class InternalTransactionTable(Base):  # type: ignore[misc, valid-type]
    __tablename__ = "internal_transaction"
    __table_args__ = (
        Index("ix_internal_transaction_partner_transaction_time", "partner", "transaction_time"),
    )

    id = Column(String(255), primary_key=True)
    partner = Column(String(255), nullable=False, index=True)
    partner_txn_id = Column(String(255), nullable=False, index=True)
    amount = Column(Numeric(20, 4), nullable=False)
    currency = Column(String(50), default="VND")
    status = Column(String(50), nullable=False)
    transaction_time = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ReconciliationResultTable(Base):  # type: ignore[misc, valid-type]
    __tablename__ = "reconciliation_result"
    __table_args__ = (
        Index(
            "ix_reconciliation_result_partner_date_status",
            "partner",
            "date",
            "reconciliation_status",
        ),
    )

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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


__all__ = [
    "Base",
    "PartnerTransactionTable",
    "InternalTransactionTable",
    "ReconciliationResultTable",
]
