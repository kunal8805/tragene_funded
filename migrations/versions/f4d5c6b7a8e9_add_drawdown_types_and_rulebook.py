"""add drawdown types and rulebook

Revision ID: f4d5c6b7a8e9
Revises: e3a9b7c2d4f1
Create Date: 2026-06-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f4d5c6b7a8e9'
down_revision = 'e3a9b7c2d4f1'
branch_labels = None
depends_on = None


DEFAULT_RULEBOOK_SECTIONS = [
    ('Balance', 'Definition:\nBalance is the amount of money currently in your trading account excluding any open trade profits or losses.\n\nExample:\nAccount Balance = $10,000\nOpen Trade Loss = -$500\nBalance remains:\n$10,000\n\nWhy It Matters:\nMany challenge rules use balance as a reference point.'),
    ('Equity', 'Definition:\nEquity is the real-time value of your account after including all open trade profits and losses.\n\nFormula:\nEquity = Balance + Floating Profit/Loss\n\nExample:\nBalance = $10,000\nOpen Loss = -$500\nEquity = $9,500\n\nWhy It Matters:\nMany prop firms calculate drawdown using equity.'),
    ('Floating Profit', 'Definition:\nProfit from trades that are still open.\n\nThe profit has not yet been locked in because the trade has not been closed.\n\nExample:\nTrade Open\nCurrent Profit = +$250\nFloating Profit = $250'),
    ('Floating Loss', 'Definition:\nLoss from trades that are still open.\n\nExample:\nTrade Open\nCurrent Loss = -$300\nFloating Loss = $300\n\nImportant:\nFloating losses reduce equity immediately.'),
    ('Daily Drawdown', 'Definition:\nMaximum loss allowed during a single trading day.\n\nExample:\nDaily Drawdown Limit = 5%\nAccount Size = $10,000\nMaximum Daily Loss = $500\n\nIf daily loss exceeds the allowed amount, the account may be breached.'),
    ('Overall Drawdown', 'Definition:\nMaximum loss allowed during the entire challenge.\n\nExample:\nOverall Drawdown = 10%\nAccount Size = $10,000\nMaximum Loss Allowed = $1,000'),
    ('Equity-Based Drawdown', 'Definition:\nDrawdown calculated using account equity.\n\nOpen trade losses count immediately.\n\nExample:\nBalance = $10,000\nOpen Loss = -$700\nEquity = $9,300\nSystem evaluates drawdown using $9,300.\n\nImportant:\nYou can breach the challenge even while trades remain open.'),
    ('Static Drawdown', 'Definition:\nDrawdown measured against fixed account limits.\n\nExample:\nAccount Size = $10,000\nMaximum Allowed Loss = $1,000\nAccount cannot fall below $9,000.'),
    ('Margin', 'Definition:\nMoney reserved by the broker to keep positions open.\n\nThe larger the trade size, the more margin is required.\n\nWhy It Matters:\nWithout sufficient margin, new trades may not open.'),
    ('Free Margin', 'Definition:\nAvailable funds that can still be used for trading.\n\nFormula:\nFree Margin = Equity - Used Margin\n\nExample:\nEquity = $10,000\nUsed Margin = $2,000\nFree Margin = $8,000'),
    ('Leverage', 'Definition:\nLeverage allows traders to control larger positions with smaller capital.\n\nExample:\n1:100 Leverage\n$100 controls approximately $10,000 worth of market exposure.\n\nImportant:\nHigher leverage increases both profit potential and risk.'),
    ('Margin Level', 'Definition:\nShows account health.\n\nFormula:\nMargin Level = (Equity / Used Margin) x 100\n\nHigher percentage = safer account.\nLower percentage = higher liquidation risk.'),
    ('Stop Out', 'Definition:\nAutomatic closing of trades by the broker when margin levels become critically low.\n\nPurpose:\nProtect the account from going negative.'),
    ('Profit Target', 'Definition:\nPercentage gain required to pass a challenge phase.\n\nExample:\nProfit Target = 8%\nAccount Size = $10,000\nRequired Profit = $800'),
    ('Trading Days', 'Definition:\nMinimum number of trading days required before challenge completion.\n\nExample:\nMinimum Trading Days = 5\n\nEven if profit target is reached in one day, the trader may still need additional trading days to qualify.'),
]


def upgrade():
    with op.batch_alter_table('challenge_template') as batch_op:
        batch_op.add_column(sa.Column('phase1_daily_dd_type', sa.String(length=20), nullable=False, server_default='equity'))
        batch_op.add_column(sa.Column('phase1_overall_dd_type', sa.String(length=20), nullable=False, server_default='equity'))
        batch_op.add_column(sa.Column('phase2_daily_dd_type', sa.String(length=20), nullable=False, server_default='equity'))
        batch_op.add_column(sa.Column('phase2_overall_dd_type', sa.String(length=20), nullable=False, server_default='equity'))
        batch_op.add_column(sa.Column('instant_daily_dd_type', sa.String(length=20), nullable=False, server_default='equity'))
        batch_op.add_column(sa.Column('instant_overall_dd_type', sa.String(length=20), nullable=False, server_default='equity'))

    with op.batch_alter_table('challenge_purchase') as batch_op:
        batch_op.add_column(sa.Column('daily_start_balance', sa.Float(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('day_start_balance', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('phase_day_start_balance', sa.Float(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('phase_lowest_balance_today', sa.Float(), nullable=True, server_default='0'))

    with op.batch_alter_table('violation_evidence') as batch_op:
        batch_op.add_column(sa.Column('drawdown_model', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('day_start_value', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('lowest_value', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('current_value', sa.Float(), nullable=True))

    with op.batch_alter_table('payment') as batch_op:
        batch_op.add_column(sa.Column('rule_acceptance_timestamp', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('rule_acceptance_ip', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('rule_acceptance_user_agent', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('challenge_version_snapshot', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('rule_version_snapshot', sa.String(length=50), nullable=True))

    op.create_table(
        'rulebook_section',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['user.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_rulebook_section_title'), 'rulebook_section', ['title'], unique=False)
    op.create_index(op.f('ix_rulebook_section_display_order'), 'rulebook_section', ['display_order'], unique=False)
    op.create_index(op.f('ix_rulebook_section_is_active'), 'rulebook_section', ['is_active'], unique=False)

    op.create_table(
        'purchase_rule_acceptance',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('challenge_template_id', sa.Integer(), nullable=False),
        sa.Column('challenge_purchase_id', sa.Integer(), nullable=True),
        sa.Column('payment_id', sa.Integer(), nullable=True),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ip_address', sa.String(length=50), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('challenge_version_snapshot', sa.JSON(), nullable=False),
        sa.Column('rule_version_snapshot', sa.String(length=50), nullable=False, server_default='rulebook-v1'),
        sa.ForeignKeyConstraint(['challenge_purchase_id'], ['challenge_purchase.id']),
        sa.ForeignKeyConstraint(['challenge_template_id'], ['challenge_template.id']),
        sa.ForeignKeyConstraint(['payment_id'], ['payment.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_purchase_rule_acceptance_user_id'), 'purchase_rule_acceptance', ['user_id'], unique=False)
    op.create_index(op.f('ix_purchase_rule_acceptance_challenge_template_id'), 'purchase_rule_acceptance', ['challenge_template_id'], unique=False)
    op.create_index(op.f('ix_purchase_rule_acceptance_challenge_purchase_id'), 'purchase_rule_acceptance', ['challenge_purchase_id'], unique=False)
    op.create_index(op.f('ix_purchase_rule_acceptance_payment_id'), 'purchase_rule_acceptance', ['payment_id'], unique=False)
    op.create_index(op.f('ix_purchase_rule_acceptance_accepted_at'), 'purchase_rule_acceptance', ['accepted_at'], unique=False)

    rulebook = sa.table(
        'rulebook_section',
        sa.column('title', sa.String),
        sa.column('content', sa.Text),
        sa.column('display_order', sa.Integer),
        sa.column('is_active', sa.Boolean),
        sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('updated_at', sa.DateTime(timezone=True)),
    )
    now = sa.func.now()
    op.bulk_insert(rulebook, [
        {
            'title': title,
            'content': content,
            'display_order': idx,
            'is_active': True,
            'created_at': now,
            'updated_at': now,
        }
        for idx, (title, content) in enumerate(DEFAULT_RULEBOOK_SECTIONS, start=1)
    ])


def downgrade():
    op.drop_index(op.f('ix_purchase_rule_acceptance_accepted_at'), table_name='purchase_rule_acceptance')
    op.drop_index(op.f('ix_purchase_rule_acceptance_payment_id'), table_name='purchase_rule_acceptance')
    op.drop_index(op.f('ix_purchase_rule_acceptance_challenge_purchase_id'), table_name='purchase_rule_acceptance')
    op.drop_index(op.f('ix_purchase_rule_acceptance_challenge_template_id'), table_name='purchase_rule_acceptance')
    op.drop_index(op.f('ix_purchase_rule_acceptance_user_id'), table_name='purchase_rule_acceptance')
    op.drop_table('purchase_rule_acceptance')

    op.drop_index(op.f('ix_rulebook_section_is_active'), table_name='rulebook_section')
    op.drop_index(op.f('ix_rulebook_section_display_order'), table_name='rulebook_section')
    op.drop_index(op.f('ix_rulebook_section_title'), table_name='rulebook_section')
    op.drop_table('rulebook_section')

    with op.batch_alter_table('payment') as batch_op:
        batch_op.drop_column('rule_version_snapshot')
        batch_op.drop_column('challenge_version_snapshot')
        batch_op.drop_column('rule_acceptance_user_agent')
        batch_op.drop_column('rule_acceptance_ip')
        batch_op.drop_column('rule_acceptance_timestamp')

    with op.batch_alter_table('violation_evidence') as batch_op:
        batch_op.drop_column('current_value')
        batch_op.drop_column('lowest_value')
        batch_op.drop_column('day_start_value')
        batch_op.drop_column('drawdown_model')

    with op.batch_alter_table('challenge_purchase') as batch_op:
        batch_op.drop_column('phase_lowest_balance_today')
        batch_op.drop_column('phase_day_start_balance')
        batch_op.drop_column('day_start_balance')
        batch_op.drop_column('daily_start_balance')

    with op.batch_alter_table('challenge_template') as batch_op:
        batch_op.drop_column('instant_overall_dd_type')
        batch_op.drop_column('instant_daily_dd_type')
        batch_op.drop_column('phase2_overall_dd_type')
        batch_op.drop_column('phase2_daily_dd_type')
        batch_op.drop_column('phase1_overall_dd_type')
        batch_op.drop_column('phase1_daily_dd_type')
