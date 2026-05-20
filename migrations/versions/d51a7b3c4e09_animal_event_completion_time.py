"""add completion_time to animal_event

Revision ID: d51a7b3c4e09
Revises: c4f8e1a92d50
Create Date: 2026-05-20 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd51a7b3c4e09'
down_revision = 'c4f8e1a92d50'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('animal_event', schema=None) as batch_op:
        batch_op.add_column(sa.Column('completion_time', sa.Time(), nullable=True))
    with op.batch_alter_table('animal_event_version', schema=None) as batch_op:
        batch_op.add_column(sa.Column('completion_time', sa.Time(), autoincrement=False, nullable=True))


def downgrade():
    with op.batch_alter_table('animal_event_version', schema=None) as batch_op:
        batch_op.drop_column('completion_time')
    with op.batch_alter_table('animal_event', schema=None) as batch_op:
        batch_op.drop_column('completion_time')
