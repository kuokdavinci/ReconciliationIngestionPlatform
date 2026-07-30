"""Add ingestion_key and unique transaction identity.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "partner_transaction",
        sa.Column("ingestion_key", sa.String(length=255), nullable=True),
    )
    op.execute(
        """
        UPDATE partner_transaction
        SET ingestion_key = COALESCE(NULLIF(ingestion_key, ''), partner_id)
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM partner_transaction
                GROUP BY identify, ingestion_key
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'Cannot enable ingestion idempotency: duplicate '
                              '(identify, ingestion_key) values exist',
                    HINT = 'Resolve duplicate partner_transaction rows, then rerun migration 0002';
            END IF;
        END
        $$;
        """
    )
    op.alter_column("partner_transaction", "ingestion_key", nullable=False)
    op.create_index(
        "ix_partner_transaction_ingestion_key",
        "partner_transaction",
        ["ingestion_key"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_partner_transaction_identify_ingestion_key",
        "partner_transaction",
        ["identify", "ingestion_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_partner_transaction_identify_ingestion_key",
        "partner_transaction",
        type_="unique",
    )
    op.drop_index(
        "ix_partner_transaction_ingestion_key",
        table_name="partner_transaction",
    )
    op.drop_column("partner_transaction", "ingestion_key")
