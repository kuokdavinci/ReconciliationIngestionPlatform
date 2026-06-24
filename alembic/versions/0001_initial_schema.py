"""Initial schema — partner_transaction, internal_transaction, reconciliation_result

Revision ID: 0001
Revises:
Create Date: 2026-06-24
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'partner_transaction',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('request_id', UUID(as_uuid=True), nullable=False),
        sa.Column('identify', sa.String(255), nullable=False, index=True),
        sa.Column('workflow_type', sa.String(255), nullable=False),
        sa.Column('reconciliation_date', sa.DateTime(), nullable=False, index=True),
        sa.Column('operation_status', sa.String(50), server_default='IN_PROGRESS'),
        sa.Column('reconciliation_status', sa.String(50), server_default=''),
        sa.Column('connector_data', sa.Text(), server_default=''),
        sa.Column('extra_data', sa.Text(), server_default=''),
        sa.Column('source_file_id', UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('partner_id', sa.String(255), nullable=False),
        sa.Column('partner_trace', sa.String(255), nullable=True, index=True),
        sa.Column('partner_status', sa.String(255), nullable=False),
        sa.Column('partner_amount', sa.Numeric(20, 4), nullable=False),
        sa.Column('partner_currency', sa.String(50), nullable=False),
        sa.Column('partner_trans_date', sa.DateTime(), nullable=True),
        sa.Column('partner_metadata', JSONB(), server_default='{}'),
        sa.Column('created_by', sa.String(255), server_default='system'),
        sa.Column('created_date', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('last_modified_by', sa.String(255), server_default='system'),
        sa.Column('last_modified_date', sa.DateTime(), server_default=sa.func.now()),
        if_not_exists=True,
    )
    op.create_table(
        'internal_transaction',
        sa.Column('id', sa.String(255), primary_key=True),
        sa.Column('partner', sa.String(255), nullable=False, index=True),
        sa.Column('partner_txn_id', sa.String(255), nullable=False, index=True),
        sa.Column('amount', sa.Numeric(20, 4), nullable=False),
        sa.Column('currency', sa.String(50), server_default='VND'),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('transaction_time', sa.DateTime(), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        if_not_exists=True,
    )
    op.create_table(
        'reconciliation_result',
        sa.Column('id', sa.String(255), primary_key=True),
        sa.Column('partner', sa.String(255), nullable=False, index=True),
        sa.Column('date', sa.String(10), nullable=False, index=True),
        sa.Column('partner_txn_id', sa.String(255), nullable=False),
        sa.Column('internal_txn_id', sa.String(255), nullable=True),
        sa.Column('partner_amount', sa.Numeric(20, 4), nullable=True),
        sa.Column('internal_amount', sa.Numeric(20, 4), nullable=True),
        sa.Column('partner_status', sa.String(50), nullable=True),
        sa.Column('internal_status', sa.String(50), nullable=True),
        sa.Column('reconciliation_status', sa.String(50), nullable=False, index=True),
        sa.Column('reconciliation_run_id', sa.String(255), nullable=True, index=True),
        sa.Column('source_file_id', sa.String(255), nullable=True, index=True),
        sa.Column('scope_type', sa.String(50), nullable=True),
        sa.Column('mapping_version', sa.String(50), nullable=True),
        sa.Column('partner_record_id', sa.String(255), nullable=True),
        sa.Column('internal_record_id', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table('reconciliation_result')
    op.drop_table('internal_transaction')
    op.drop_table('partner_transaction')
