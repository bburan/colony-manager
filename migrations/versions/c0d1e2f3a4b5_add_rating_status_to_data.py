"""Add is_rated and rating_note to Data.

Populated by the nightly ``flask data sync-rating`` job, which calls
``DataTypeDescription.get_rating_status()`` for every Data row whose
description class has ``supports_rating = True``.  Existing rows are
left NULL (not applicable / not yet computed).

Revision ID: c0d1e2f3a4b5
Revises: b1c2d3e4f5a6
Create Date: 2026-06-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c0d1e2f3a4b5'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('data') as batch_op:
        batch_op.add_column(sa.Column('is_rated',    sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('rating_note', sa.Text(),    nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('data') as batch_op:
        batch_op.drop_column('rating_note')
        batch_op.drop_column('is_rated')
