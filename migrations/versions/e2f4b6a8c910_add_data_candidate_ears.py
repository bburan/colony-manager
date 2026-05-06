"""Add data_candidate_ears M2M.

Mirrors ``data_candidate_animals``: links a Data row to the resolved Ear
rows derived from ``parsed['side']`` + ``parsed['animal_id']`` at sync
time. Lets the ear page surface unmatched candidate confocal images even
when the matcher couldn't find a specific ConfocalImage row (e.g.
unknown frequency or image type).

Revision ID: e2f4b6a8c910
Revises: d9f1e3b5c708
Create Date: 2026-05-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e2f4b6a8c910'
down_revision: Union[str, Sequence[str], None] = 'd9f1e3b5c708'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


VERSION_PK_COLUMNS = (
    sa.Column('transaction_id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('end_transaction_id', sa.BigInteger(), nullable=True),
    sa.Column('operation_type', sa.SmallInteger(), nullable=False),
)


def _add_version_indexes(table_name: str, pk_cols: list[str]) -> None:
    op.create_index(
        op.f(f'ix_{table_name}_end_transaction_id'),
        table_name, ['end_transaction_id'], unique=False,
    )
    op.create_index(
        op.f(f'ix_{table_name}_operation_type'),
        table_name, ['operation_type'], unique=False,
    )
    op.create_index(
        f'ix_{table_name}_pk_transaction_id',
        table_name,
        pk_cols + [sa.literal_column('transaction_id DESC')],
        unique=False,
    )
    op.create_index(
        f'ix_{table_name}_pk_validity',
        table_name,
        pk_cols + ['transaction_id', 'end_transaction_id'],
        unique=False,
    )
    op.create_index(
        op.f(f'ix_{table_name}_transaction_id'),
        table_name, ['transaction_id'], unique=False,
    )


def _drop_version_indexes(table_name: str) -> None:
    op.drop_index(op.f(f'ix_{table_name}_transaction_id'), table_name=table_name)
    op.drop_index(f'ix_{table_name}_pk_validity', table_name=table_name)
    op.drop_index(f'ix_{table_name}_pk_transaction_id', table_name=table_name)
    op.drop_index(op.f(f'ix_{table_name}_operation_type'), table_name=table_name)
    op.drop_index(op.f(f'ix_{table_name}_end_transaction_id'), table_name=table_name)


def upgrade() -> None:
    op.create_table(
        'data_candidate_ears',
        sa.Column('data_id', sa.Integer(), nullable=False),
        sa.Column('ear_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ['data_id'], ['data.id'],
            name=op.f('fk_data_candidate_ears_data_id_data'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['ear_id'], ['ear.id'],
            name=op.f('fk_data_candidate_ears_ear_id_ear'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint(
            'data_id', 'ear_id',
            name=op.f('pk_data_candidate_ears'),
        ),
    )
    op.create_table(
        'data_candidate_ears_version',
        sa.Column('data_id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('ear_id', sa.Integer(), autoincrement=False, nullable=False),
        *VERSION_PK_COLUMNS,
        sa.PrimaryKeyConstraint(
            'data_id', 'ear_id', 'transaction_id',
            name=op.f('pk_data_candidate_ears_version'),
        ),
    )
    _add_version_indexes('data_candidate_ears_version', ['data_id', 'ear_id'])


def downgrade() -> None:
    _drop_version_indexes('data_candidate_ears_version')
    op.drop_table('data_candidate_ears_version')
    op.drop_table('data_candidate_ears')
