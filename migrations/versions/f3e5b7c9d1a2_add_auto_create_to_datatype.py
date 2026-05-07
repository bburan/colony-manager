"""Add auto_create option to DataType.

Revision ID: f3e5b7c9d1a2
Revises: e2f4b6a8c910
Create Date: 2026-05-07 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f3e5b7c9d1a2'
down_revision = 'e2f4b6a8c910'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('data_type', sa.Column('auto_create', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('data_type_version', sa.Column('auto_create', sa.Boolean(), autoincrement=False, nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    version_cols = {c['name'] for c in inspector.get_columns('data_type_version')}
    if 'auto_create' in version_cols:
        op.drop_column('data_type_version', 'auto_create')
    op.drop_column('data_type', 'auto_create')
