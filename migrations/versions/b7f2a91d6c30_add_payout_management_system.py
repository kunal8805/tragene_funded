"""add payout management system

Revision ID: b7f2a91d6c30
Revises: 9e6acc10156b
Create Date: 2026-06-04 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b7f2a91d6c30'
down_revision = '9e6acc10156b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('payout') as batch_op:
        batch_op.add_column(sa.Column('username_snapshot', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('challenge_name_snapshot', sa.String(length=150), nullable=True))
        batch_op.add_column(sa.Column('account_type_snapshot', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('account_size_snapshot', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('available_profit_snapshot', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('rejection_reason', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('expected_payment_time', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('account_holder_name', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('upi_id', sa.String(length=120), nullable=True))
        batch_op.create_index('ix_payout_approved_at', ['approved_at'])
        batch_op.create_index('ix_payout_reviewed_at', ['reviewed_at'])
        batch_op.create_index('ix_payout_paid_at', ['paid_at'])

    op.create_table(
        'payout_audit_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('payout_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('admin_user_id', sa.Integer(), nullable=True),
        sa.Column('admin_username', sa.String(length=120), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['admin_user_id'], ['user.id']),
        sa.ForeignKeyConstraint(['payout_id'], ['payout.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_payout_audit_log_action', 'payout_audit_log', ['action'])
    op.create_index('ix_payout_audit_log_admin_user_id', 'payout_audit_log', ['admin_user_id'])
    op.create_index('ix_payout_audit_log_created_at', 'payout_audit_log', ['created_at'])
    op.create_index('ix_payout_audit_log_payout_id', 'payout_audit_log', ['payout_id'])


def downgrade():
    op.drop_index('ix_payout_audit_log_payout_id', table_name='payout_audit_log')
    op.drop_index('ix_payout_audit_log_created_at', table_name='payout_audit_log')
    op.drop_index('ix_payout_audit_log_admin_user_id', table_name='payout_audit_log')
    op.drop_index('ix_payout_audit_log_action', table_name='payout_audit_log')
    op.drop_table('payout_audit_log')

    with op.batch_alter_table('payout') as batch_op:
        batch_op.drop_index('ix_payout_paid_at')
        batch_op.drop_index('ix_payout_reviewed_at')
        batch_op.drop_index('ix_payout_approved_at')
        batch_op.drop_column('upi_id')
        batch_op.drop_column('account_holder_name')
        batch_op.drop_column('paid_at')
        batch_op.drop_column('reviewed_at')
        batch_op.drop_column('approved_at')
        batch_op.drop_column('expected_payment_time')
        batch_op.drop_column('rejection_reason')
        batch_op.drop_column('available_profit_snapshot')
        batch_op.drop_column('account_size_snapshot')
        batch_op.drop_column('account_type_snapshot')
        batch_op.drop_column('challenge_name_snapshot')
        batch_op.drop_column('username_snapshot')
