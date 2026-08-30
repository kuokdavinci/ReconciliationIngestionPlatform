"""Add timestamp evidence and source timestamp basis markers.

Revision ID: 0004
Revises: 0003
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "partner_transaction",
        sa.Column(
            "timestamp_basis",
            sa.String(length=32),
            nullable=False,
            server_default="LEGACY_STORED",
        ),
    )
    op.add_column("reconciliation_result", sa.Column("reconciliation_key", sa.String(255)))
    op.add_column("reconciliation_result", sa.Column("partner_trans_date", sa.DateTime()))
    op.add_column(
        "reconciliation_result", sa.Column("internal_transaction_time", sa.DateTime())
    )
    op.add_column(
        "reconciliation_result",
        sa.Column(
            "timestamp_status",
            sa.String(20),
            nullable=False,
            server_default="NOT_EVALUATED",
        ),
    )
    op.create_index(
        "ix_reconciliation_result_partner_date_timestamp_status",
        "reconciliation_result",
        ["partner", "date", "timestamp_status"],
    )
    op.add_column(
        "reconciliation_result",
        sa.Column("timestamp_delta_seconds", sa.Numeric(20, 6), nullable=True),
    )
    op.add_column(
        "reconciliation_result",
        sa.Column("timestamp_tolerance_seconds", sa.Numeric(20, 0), nullable=True),
    )
    op.add_column(
        "reconciliation_result", sa.Column("timestamp_timezone", sa.String(64), nullable=True)
    )
    op.add_column(
        "reconciliation_result",
        sa.Column(
            "timestamp_basis",
            sa.String(32),
            nullable=False,
            server_default="LEGACY_STORED",
        ),
    )
    op.add_column(
        "reconciliation_result",
        sa.Column(
            "ambiguous_partner_record_ids",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "reconciliation_result",
        sa.Column(
            "ambiguous_internal_record_ids",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reconciliation_result_partner_date_timestamp_status",
        table_name="reconciliation_result",
    )
    for column in (
        "ambiguous_internal_record_ids",
        "ambiguous_partner_record_ids",
        "timestamp_basis",
        "timestamp_timezone",
        "timestamp_tolerance_seconds",
        "timestamp_delta_seconds",
        "timestamp_status",
        "internal_transaction_time",
        "partner_trans_date",
        "reconciliation_key",
    ):
        op.drop_column("reconciliation_result", column)
    op.drop_column("partner_transaction", "timestamp_basis")
