"""merge migration heads

Revision ID: 8c2b0a43f06b
Revises: 01e1bbf6604e, 9f58ef111346
Create Date: 2026-05-22 15:42:55.752347

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8c2b0a43f06b'
down_revision = ('01e1bbf6604e', '9f58ef111346')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
