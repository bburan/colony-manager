"""Add ``sync_job`` table for background sync/rematch runs.

Revision ID: 2d4f6a8c0b13
Revises: 1c3a5e7b9d10
Create Date: 2026-05-07 00:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '2d4f6a8c0b13'
down_revision: Union[str, Sequence[str], None] = 'f3e5b7c9d1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sync_job',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'datatype_id', sa.Integer(),
            sa.ForeignKey('data_type.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('enqueued_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
    )
    op.create_index(
        'ix_sync_job_enqueued_at', 'sync_job', ['enqueued_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_sync_job_enqueued_at', table_name='sync_job')
    op.drop_table('sync_job')
