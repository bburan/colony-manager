"""Add rq_job_id column to sync_job.

Lets the worker-boot stale-job sweep tell "still queued in Redis"
apart from "worker died mid-execution" — without it we couldn't
distinguish a pending job legitimately waiting for the worker from
a job whose worker process got recycled before it could finish.

Nullable because existing rows pre-date RQ entirely, and the
synchronous/test execution paths don't always go through RQ.

Revision ID: b7c2a3f9e081
Revises: a8b1c2d3e4f5
Create Date: 2026-05-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c2a3f9e081'
down_revision: Union[str, Sequence[str], None] = 'a8b1c2d3e4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'sync_job',
        sa.Column('rq_job_id', sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('sync_job', 'rq_job_id')
