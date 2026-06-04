"""Tag name uniqueness scoped to parent instead of global.

Hierarchical tags (AnimalTag, AnimalEventTag, EarTag) previously
enforced a global unique constraint on ``name``, preventing reuse of the
same name under different parents. Replace each global constraint with a
composite unique constraint on ``(name, parent_id)`` so sibling names
must be distinct but the same name may appear under different parents.

Revision ID: b1c2d3e4f5a6
Revises: f1a2b3c4d5e6
Create Date: 2026-06-04 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ('animal_tag', 'animal_event_tag', 'ear_tag'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_constraint(f'uq_{table}_name', type_='unique')
            batch_op.create_unique_constraint(
                f'uq_{table}_name', ['name', 'parent_id']
            )


def downgrade() -> None:
    for table in ('animal_tag', 'animal_event_tag', 'ear_tag'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_constraint(f'uq_{table}_name', type_='unique')
            batch_op.create_unique_constraint(f'uq_{table}_name', ['name'])
