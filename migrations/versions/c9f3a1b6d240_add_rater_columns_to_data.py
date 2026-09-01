"""Add rater_count and raters to data

Persists who rated a file and how many raters, populated by the
sync-rating job from a description class's get_rating_status()['raters']
(currently ABR waveform picks). Lets the rating-review page filter by
rater coverage (single vs multiple) and by rater identity.

Revision ID: c9f3a1b6d240
Revises: b7e2f4a19c33
Create Date: 2026-08-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c9f3a1b6d240'
down_revision: Union[str, Sequence[str], None] = 'b7e2f4a19c33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('data', sa.Column('rater_count', sa.Integer(), nullable=True))
    op.add_column(
        'data',
        sa.Column('raters', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('data', 'raters')
    op.drop_column('data', 'rater_count')
