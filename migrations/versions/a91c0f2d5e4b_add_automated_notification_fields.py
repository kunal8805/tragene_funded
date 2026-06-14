"""add automated notification fields

Revision ID: a91c0f2d5e4b
Revises: f4d5c6b7a8e9
Create Date: 2026-06-14 15:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a91c0f2d5e4b'
down_revision = 'f4d5c6b7a8e9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('notification', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notification_type', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('action_url', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('icon', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('dedupe_key', sa.String(length=120), nullable=True))
        batch_op.create_index(batch_op.f('ix_notification_notification_type'), ['notification_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_notification_dedupe_key'), ['dedupe_key'], unique=False)

    op.execute("UPDATE notification SET notification_type = 'system' WHERE notification_type IS NULL")


def downgrade():
    with op.batch_alter_table('notification', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notification_dedupe_key'))
        batch_op.drop_index(batch_op.f('ix_notification_notification_type'))
        batch_op.drop_column('dedupe_key')
        batch_op.drop_column('icon')
        batch_op.drop_column('action_url')
        batch_op.drop_column('notification_type')
