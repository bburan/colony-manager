"""Add Data.analyze

Marks which of a target's replicate files staff should analyze — e.g. one
of two confocal images of the same ear/frequency. Separate from
``Data.status`` (file quality, partly sync-managed). NULL means Not set,
which is still analyzed — exactly how every existing file behaves today —
so no backfill is needed.

Revision ID: a3c8e5f17d42
Revises: e1b4d7c3a920
Create Date: 2026-09-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3c8e5f17d42'
down_revision: Union[str, Sequence[str], None] = 'e1b4d7c3a920'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('data', sa.Column('analyze', sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column('data', 'analyze')
