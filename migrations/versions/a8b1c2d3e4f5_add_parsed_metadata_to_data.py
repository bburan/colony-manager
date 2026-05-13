"""Add parsed_metadata JSON column to Data.

Populated by the sync / rematch jobs at write time so the GUI doesn't
have to re-run description-class parsers on every page render. Existing
rows are left NULL; running ``rematch (force)`` for each DataType will
backfill them.

Revision ID: a8b1c2d3e4f5
Revises: 7c3d9e1f4a86
Create Date: 2026-05-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a8b1c2d3e4f5'
down_revision: Union[str, Sequence[str], None] = '7c3d9e1f4a86'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('data') as batch_op:
        batch_op.add_column(sa.Column('parsed_metadata', sa.JSON(), nullable=True))

    try:
        with op.batch_alter_table('data_version') as batch_op:
            batch_op.add_column(sa.Column(
                'parsed_metadata', sa.JSON(),
                autoincrement=False, nullable=True,
            ))
    except Exception:
        pass


def downgrade() -> None:
    try:
        with op.batch_alter_table('data_version') as batch_op:
            batch_op.drop_column('parsed_metadata')
    except Exception:
        pass

    with op.batch_alter_table('data') as batch_op:
        batch_op.drop_column('parsed_metadata')
