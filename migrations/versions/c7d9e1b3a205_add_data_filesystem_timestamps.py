"""Add filesystem timestamps to Data: mtime, ctime, discovered_at.

Captured by the sync script the first time a file/folder is discovered.

Revision ID: c7d9e1b3a205
Revises: a1b2c3d4e5f6
Create Date: 2026-05-05 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7d9e1b3a205'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_COLUMNS = ('mtime', 'ctime', 'discovered_at')


def upgrade() -> None:
    with op.batch_alter_table('data') as batch_op:
        for col in NEW_COLUMNS:
            batch_op.add_column(sa.Column(col, sa.DateTime(), nullable=True))

    try:
        with op.batch_alter_table('data_version') as batch_op:
            for col in NEW_COLUMNS:
                batch_op.add_column(sa.Column(col, sa.DateTime(), autoincrement=False, nullable=True))
    except Exception:
        pass


def downgrade() -> None:
    try:
        with op.batch_alter_table('data_version') as batch_op:
            for col in NEW_COLUMNS:
                batch_op.drop_column(col)
    except Exception:
        pass

    with op.batch_alter_table('data') as batch_op:
        for col in NEW_COLUMNS:
            batch_op.drop_column(col)
