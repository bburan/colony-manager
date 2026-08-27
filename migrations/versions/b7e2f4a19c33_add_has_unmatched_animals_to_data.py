"""Add has_unmatched_animals flag to data

Marks a Data row whose filename named one or more animal IDs that had no
matching Animal at sync time (even when other IDs in the same filename
matched). Populated by the sync/rematch code; drives the data-review page
filter. Existing rows default to false and are corrected on the next sync
or a force-rematch.

Revision ID: b7e2f4a19c33
Revises: c0d1e2f3a4b5
Create Date: 2026-08-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e2f4a19c33'
down_revision: Union[str, Sequence[str], None] = 'c0d1e2f3a4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'data',
        sa.Column(
            'has_unmatched_animals', sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('data', 'has_unmatched_animals')
