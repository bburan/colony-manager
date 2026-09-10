"""Add analyzed_by and analyzed_at to data

Persists analysis attribution and recency, populated by the sync-rating
job from a description class's get_rating_status() ('analyzed_by' /
'analyzed_at'). analyzed_by is the cross-datatype "who worked this
analysis" list (ABR mirrors its raters into it; IHC/OHC and synaptograms
derive it from the analysis file's meta.history user entries); analyzed_at
is when the analysis was last modified. Both back the Analysis Scoreboard.

Revision ID: d2e4f6a8b1c3
Revises: c9f3a1b6d240
Create Date: 2026-09-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd2e4f6a8b1c3'
down_revision: Union[str, Sequence[str], None] = 'c9f3a1b6d240'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'data',
        sa.Column('analyzed_by', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column('data', sa.Column('analyzed_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('data', 'analyzed_at')
    op.drop_column('data', 'analyzed_by')
