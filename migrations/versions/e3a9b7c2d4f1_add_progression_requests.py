"""Add progression requests

Revision ID: e3a9b7c2d4f1
Revises: be633688cce9
Create Date: 2026-06-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e3a9b7c2d4f1'
down_revision = 'be633688cce9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'progression_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('challenge_purchase_id', sa.Integer(), nullable=False),
        sa.Column('request_type', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('admin_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('declined_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['challenge_purchase_id'], ['challenge_purchase.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_progression_requests_user_id'), 'progression_requests', ['user_id'], unique=False)
    op.create_index(op.f('ix_progression_requests_challenge_purchase_id'), 'progression_requests', ['challenge_purchase_id'], unique=False)
    op.create_index(op.f('ix_progression_requests_request_type'), 'progression_requests', ['request_type'], unique=False)
    op.create_index(op.f('ix_progression_requests_status'), 'progression_requests', ['status'], unique=False)
    op.create_index(op.f('ix_progression_requests_created_at'), 'progression_requests', ['created_at'], unique=False)
    op.create_index('idx_progression_request_user_status', 'progression_requests', ['user_id', 'status'], unique=False)
    op.create_index('idx_progression_request_challenge_type_status', 'progression_requests', ['challenge_purchase_id', 'request_type', 'status'], unique=False)


def downgrade():
    op.drop_index('idx_progression_request_challenge_type_status', table_name='progression_requests')
    op.drop_index('idx_progression_request_user_status', table_name='progression_requests')
    op.drop_index(op.f('ix_progression_requests_created_at'), table_name='progression_requests')
    op.drop_index(op.f('ix_progression_requests_status'), table_name='progression_requests')
    op.drop_index(op.f('ix_progression_requests_request_type'), table_name='progression_requests')
    op.drop_index(op.f('ix_progression_requests_challenge_purchase_id'), table_name='progression_requests')
    op.drop_index(op.f('ix_progression_requests_user_id'), table_name='progression_requests')
    op.drop_table('progression_requests')
