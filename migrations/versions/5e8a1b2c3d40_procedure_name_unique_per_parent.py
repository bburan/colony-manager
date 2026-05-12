"""Make AnimalProcedure name unique per parent rather than globally.

Revision ID: 5e8a1b2c3d40
Revises: 2d4f6a8c0b13
Create Date: 2026-05-12 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5e8a1b2c3d40'
down_revision: Union[str, Sequence[str], None] = '2d4f6a8c0b13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('animal_procedure', schema=None) as batch_op:
        batch_op.drop_constraint('uq_animal_procedure_name', type_='unique')
        batch_op.create_unique_constraint(
            'uq_animal_procedure_parent_id_name', ['parent_id', 'name']
        )
    op.create_index(
        'uq_animal_procedure_name_root',
        'animal_procedure',
        ['name'],
        unique=True,
        postgresql_where=sa.text('parent_id IS NULL'),
        sqlite_where=sa.text('parent_id IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_animal_procedure_name_root', table_name='animal_procedure')
    with op.batch_alter_table('animal_procedure', schema=None) as batch_op:
        batch_op.drop_constraint('uq_animal_procedure_parent_id_name', type_='unique')
        batch_op.create_unique_constraint('uq_animal_procedure_name', ['name'])
