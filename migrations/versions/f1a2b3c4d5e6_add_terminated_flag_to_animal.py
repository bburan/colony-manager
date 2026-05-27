"""Add terminated boolean flag to animal.

An explicit ``terminated`` flag lets historical animals be marked
as terminated even when the exact termination date is unknown.
``is_active`` is now derived from this flag rather than from a
NULL-check on ``termination_date``.

The upgrade backfills existing rows: any animal that already has a
non-NULL ``termination_date`` is treated as terminated.

Revision ID: f1a2b3c4d5e6
Revises: e5a7c9b1d3f2
Create Date: 2026-05-27 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e5a7c9b1d3f2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add the column with a server-side default of false so existing rows
    # get the correct value before we run the backfill UPDATE.
    with op.batch_alter_table('animal', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'terminated',
                sa.Boolean(),
                nullable=False,
                server_default=sa.text('false'),
            )
        )

    # Backfill: animals with a termination_date already set are terminated.
    op.execute(
        sa.text(
            'UPDATE animal SET terminated = true WHERE termination_date IS NOT NULL'
        )
    )


def downgrade() -> None:
    with op.batch_alter_table('animal', schema=None) as batch_op:
        batch_op.drop_column('terminated')
