"""Add composite indexes for reconciliation query shapes."""

from typing import Sequence, Union

from alembic import op


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_partner_transaction_identify_reconciliation_date",
        "partner_transaction",
        ["identify", "reconciliation_date"],
    )
    op.create_index(
        "ix_internal_transaction_partner_transaction_time",
        "internal_transaction",
        ["partner", "transaction_time"],
    )
    op.create_index(
        "ix_reconciliation_result_partner_date_status",
        "reconciliation_result",
        ["partner", "date", "reconciliation_status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reconciliation_result_partner_date_status",
        table_name="reconciliation_result",
    )
    op.drop_index(
        "ix_internal_transaction_partner_transaction_time",
        table_name="internal_transaction",
    )
    op.drop_index(
        "ix_partner_transaction_identify_reconciliation_date",
        table_name="partner_transaction",
    )
