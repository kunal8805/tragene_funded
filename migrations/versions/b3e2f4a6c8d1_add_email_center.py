"""add email center

Revision ID: b3e2f4a6c8d1
Revises: 071deb0d1bab
Create Date: 2026-07-06 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b3e2f4a6c8d1'
down_revision = '071deb0d1bab'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'email_template',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('slug', sa.String(length=140), nullable=False),
        sa.Column('category', sa.String(length=40), nullable=True),
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column('html_body', sa.Text(), nullable=False),
        sa.Column('text_body', sa.Text(), nullable=True),
        sa.Column('variables', sa.JSON(), nullable=True),
        sa.Column('channel', sa.String(length=30), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['user.id']),
        sa.ForeignKeyConstraint(['updated_by'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug')
    )
    op.create_index('ix_email_template_name', 'email_template', ['name'])
    op.create_index('ix_email_template_slug', 'email_template', ['slug'])
    op.create_index('ix_email_template_category', 'email_template', ['category'])
    op.create_index('ix_email_template_channel', 'email_template', ['channel'])
    op.create_index('ix_email_template_is_active', 'email_template', ['is_active'])
    op.create_index('ix_email_template_created_at', 'email_template', ['created_at'])

    op.create_table(
        'email_automation_rule',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=80), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('event', sa.String(length=80), nullable=False),
        sa.Column('template_id', sa.Integer(), nullable=True),
        sa.Column('subject_override', sa.String(length=255), nullable=True),
        sa.Column('html_override', sa.Text(), nullable=True),
        sa.Column('channel', sa.String(length=30), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=True),
        sa.Column('is_paused', sa.Boolean(), nullable=True),
        sa.Column('is_system', sa.Boolean(), nullable=True),
        sa.Column('once_scope', sa.String(length=40), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['template_id'], ['email_template.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key')
    )
    op.create_index('ix_email_automation_rule_key', 'email_automation_rule', ['key'])
    op.create_index('ix_email_automation_rule_event', 'email_automation_rule', ['event'])
    op.create_index('ix_email_automation_rule_channel', 'email_automation_rule', ['channel'])
    op.create_index('ix_email_automation_rule_is_enabled', 'email_automation_rule', ['is_enabled'])
    op.create_index('ix_email_automation_rule_is_paused', 'email_automation_rule', ['is_paused'])
    op.create_index('ix_email_automation_rule_created_at', 'email_automation_rule', ['created_at'])

    op.create_table(
        'email_campaign',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('campaign_type', sa.String(length=50), nullable=True),
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column('template_id', sa.Integer(), nullable=True),
        sa.Column('audience_type', sa.String(length=80), nullable=True),
        sa.Column('audience_filters', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=True),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('recurring_rule', sa.String(length=30), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['user.id']),
        sa.ForeignKeyConstraint(['template_id'], ['email_template.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_email_campaign_name', 'email_campaign', ['name'])
    op.create_index('ix_email_campaign_campaign_type', 'email_campaign', ['campaign_type'])
    op.create_index('ix_email_campaign_audience_type', 'email_campaign', ['audience_type'])
    op.create_index('ix_email_campaign_status', 'email_campaign', ['status'])
    op.create_index('ix_email_campaign_scheduled_at', 'email_campaign', ['scheduled_at'])
    op.create_index('ix_email_campaign_created_by', 'email_campaign', ['created_by'])
    op.create_index('ix_email_campaign_created_at', 'email_campaign', ['created_at'])

    op.create_table(
        'email_campaign_recipient',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('email', sa.String(length=160), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('skipped_reason', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['campaign_id'], ['email_campaign.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_email_campaign_recipient_campaign_id', 'email_campaign_recipient', ['campaign_id'])
    op.create_index('ix_email_campaign_recipient_user_id', 'email_campaign_recipient', ['user_id'])
    op.create_index('ix_email_campaign_recipient_email', 'email_campaign_recipient', ['email'])
    op.create_index('ix_email_campaign_recipient_status', 'email_campaign_recipient', ['status'])
    op.create_index('ix_email_campaign_recipient_created_at', 'email_campaign_recipient', ['created_at'])

    op.create_table(
        'email_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('to_email', sa.String(length=160), nullable=False),
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column('template_id', sa.Integer(), nullable=True),
        sa.Column('campaign_id', sa.Integer(), nullable=True),
        sa.Column('automation_id', sa.Integer(), nullable=True),
        sa.Column('channel', sa.String(length=30), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=True),
        sa.Column('provider', sa.String(length=50), nullable=True),
        sa.Column('provider_message_id', sa.String(length=160), nullable=True),
        sa.Column('dedupe_key', sa.String(length=220), nullable=True),
        sa.Column('failed_reason', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('opened_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('clicked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('bounced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['automation_id'], ['email_automation_rule.id']),
        sa.ForeignKeyConstraint(['campaign_id'], ['email_campaign.id']),
        sa.ForeignKeyConstraint(['template_id'], ['email_template.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_email_log_user_id', 'email_log', ['user_id'])
    op.create_index('ix_email_log_to_email', 'email_log', ['to_email'])
    op.create_index('ix_email_log_template_id', 'email_log', ['template_id'])
    op.create_index('ix_email_log_campaign_id', 'email_log', ['campaign_id'])
    op.create_index('ix_email_log_automation_id', 'email_log', ['automation_id'])
    op.create_index('ix_email_log_channel', 'email_log', ['channel'])
    op.create_index('ix_email_log_status', 'email_log', ['status'])
    op.create_index('ix_email_log_provider_message_id', 'email_log', ['provider_message_id'])
    op.create_index('ix_email_log_dedupe_key', 'email_log', ['dedupe_key'])
    op.create_index('ix_email_log_sent_at', 'email_log', ['sent_at'])
    op.create_index('ix_email_log_created_at', 'email_log', ['created_at'])
    op.create_index('idx_email_log_status_created', 'email_log', ['status', 'created_at'])
    op.create_index('idx_email_log_dedupe', 'email_log', ['dedupe_key', 'status'])

    op.create_table(
        'email_preference',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('allow_emails', sa.Boolean(), nullable=True),
        sa.Column('disable_marketing', sa.Boolean(), nullable=True),
        sa.Column('disable_campaigns', sa.Boolean(), nullable=True),
        sa.Column('disable_all', sa.Boolean(), nullable=True),
        sa.Column('admin_override', sa.Boolean(), nullable=True),
        sa.Column('blocked', sa.Boolean(), nullable=True),
        sa.Column('blocked_reason', sa.String(length=255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id')
    )
    op.create_index('ix_email_preference_user_id', 'email_preference', ['user_id'])
    op.create_index('ix_email_preference_blocked', 'email_preference', ['blocked'])

    op.create_table(
        'scheduled_email',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('to_email', sa.String(length=160), nullable=True),
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column('template_id', sa.Integer(), nullable=True),
        sa.Column('html_body', sa.Text(), nullable=True),
        sa.Column('variables', sa.JSON(), nullable=True),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('recurring_rule', sa.String(length=30), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['campaign_id'], ['email_campaign.id']),
        sa.ForeignKeyConstraint(['created_by'], ['user.id']),
        sa.ForeignKeyConstraint(['template_id'], ['email_template.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_scheduled_email_campaign_id', 'scheduled_email', ['campaign_id'])
    op.create_index('ix_scheduled_email_user_id', 'scheduled_email', ['user_id'])
    op.create_index('ix_scheduled_email_scheduled_at', 'scheduled_email', ['scheduled_at'])
    op.create_index('ix_scheduled_email_status', 'scheduled_email', ['status'])
    op.create_index('ix_scheduled_email_created_at', 'scheduled_email', ['created_at'])

    op.create_table(
        'email_campaign_analytics',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=True),
        sa.Column('template_id', sa.Integer(), nullable=True),
        sa.Column('automation_id', sa.Integer(), nullable=True),
        sa.Column('metric_date', sa.Date(), nullable=False),
        sa.Column('sent', sa.Integer(), nullable=True),
        sa.Column('delivered', sa.Integer(), nullable=True),
        sa.Column('failed', sa.Integer(), nullable=True),
        sa.Column('bounced', sa.Integer(), nullable=True),
        sa.Column('opened', sa.Integer(), nullable=True),
        sa.Column('clicked', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['automation_id'], ['email_automation_rule.id']),
        sa.ForeignKeyConstraint(['campaign_id'], ['email_campaign.id']),
        sa.ForeignKeyConstraint(['template_id'], ['email_template.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_email_campaign_analytics_campaign_id', 'email_campaign_analytics', ['campaign_id'])
    op.create_index('ix_email_campaign_analytics_template_id', 'email_campaign_analytics', ['template_id'])
    op.create_index('ix_email_campaign_analytics_automation_id', 'email_campaign_analytics', ['automation_id'])
    op.create_index('ix_email_campaign_analytics_metric_date', 'email_campaign_analytics', ['metric_date'])


def downgrade():
    op.drop_table('email_campaign_analytics')
    op.drop_table('scheduled_email')
    op.drop_table('email_preference')
    op.drop_table('email_log')
    op.drop_table('email_campaign_recipient')
    op.drop_table('email_campaign')
    op.drop_table('email_automation_rule')
    op.drop_table('email_template')
