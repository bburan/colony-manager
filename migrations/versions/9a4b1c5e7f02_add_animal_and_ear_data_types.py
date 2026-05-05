"""Add Animal and Ear DataType subclasses with M2M target tables.

Adds:

* ``animal_data_type`` / ``ear_data_type`` (joint-table inheritance subclasses
  of ``data_type``)
* ``animal_data`` / ``ear_data`` (joint-table inheritance subclasses of
  ``data``)
* ``animal_data_targets`` / ``ear_data_targets`` (M2M join tables)
* matching ``_version`` shadow tables for sqlalchemy_continuum

Revision ID: 9a4b1c5e7f02
Revises: 7f1c3a8d2e91
Create Date: 2026-05-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9a4b1c5e7f02'
down_revision: Union[str, Sequence[str], None] = '7f1c3a8d2e91'
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
    # ----- animal_data_type (subclass) -----
    op.create_table(
        'animal_data_type',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['id'], ['data_type.id'], name=op.f('fk_animal_data_type_id_data_type')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_animal_data_type')),
    )
    op.create_table(
        'animal_data_type_version',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
        *VERSION_PK_COLUMNS,
        sa.PrimaryKeyConstraint('id', 'transaction_id', name=op.f('pk_animal_data_type_version')),
    )
    _add_version_indexes('animal_data_type_version', ['id'])

    # ----- ear_data_type (subclass) -----
    op.create_table(
        'ear_data_type',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['id'], ['data_type.id'], name=op.f('fk_ear_data_type_id_data_type')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ear_data_type')),
    )
    op.create_table(
        'ear_data_type_version',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
        *VERSION_PK_COLUMNS,
        sa.PrimaryKeyConstraint('id', 'transaction_id', name=op.f('pk_ear_data_type_version')),
    )
    _add_version_indexes('ear_data_type_version', ['id'])

    # ----- animal_data (subclass) -----
    op.create_table(
        'animal_data',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['id'], ['data.id'], name=op.f('fk_animal_data_id_data')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_animal_data')),
    )
    op.create_table(
        'animal_data_version',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
        *VERSION_PK_COLUMNS,
        sa.PrimaryKeyConstraint('id', 'transaction_id', name=op.f('pk_animal_data_version')),
    )
    _add_version_indexes('animal_data_version', ['id'])

    # ----- ear_data (subclass) -----
    op.create_table(
        'ear_data',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['id'], ['data.id'], name=op.f('fk_ear_data_id_data')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ear_data')),
    )
    op.create_table(
        'ear_data_version',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
        *VERSION_PK_COLUMNS,
        sa.PrimaryKeyConstraint('id', 'transaction_id', name=op.f('pk_ear_data_version')),
    )
    _add_version_indexes('ear_data_version', ['id'])

    # ----- M2M target tables -----
    op.create_table(
        'animal_data_targets',
        sa.Column('animal_data_id', sa.Integer(), nullable=False),
        sa.Column('animal_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['animal_data_id'], ['animal_data.id'], name=op.f('fk_animal_data_targets_animal_data_id_animal_data')),
        sa.ForeignKeyConstraint(['animal_id'], ['animal.id'], name=op.f('fk_animal_data_targets_animal_id_animal')),
        sa.PrimaryKeyConstraint('animal_data_id', 'animal_id', name=op.f('pk_animal_data_targets')),
    )
    op.create_table(
        'animal_data_targets_version',
        sa.Column('animal_data_id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('animal_id', sa.Integer(), autoincrement=False, nullable=False),
        *VERSION_PK_COLUMNS,
        sa.PrimaryKeyConstraint('animal_data_id', 'animal_id', 'transaction_id', name=op.f('pk_animal_data_targets_version')),
    )
    _add_version_indexes('animal_data_targets_version', ['animal_data_id', 'animal_id'])

    op.create_table(
        'ear_data_targets',
        sa.Column('ear_data_id', sa.Integer(), nullable=False),
        sa.Column('ear_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['ear_data_id'], ['ear_data.id'], name=op.f('fk_ear_data_targets_ear_data_id_ear_data')),
        sa.ForeignKeyConstraint(['ear_id'], ['ear.id'], name=op.f('fk_ear_data_targets_ear_id_ear')),
        sa.PrimaryKeyConstraint('ear_data_id', 'ear_id', name=op.f('pk_ear_data_targets')),
    )
    op.create_table(
        'ear_data_targets_version',
        sa.Column('ear_data_id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('ear_id', sa.Integer(), autoincrement=False, nullable=False),
        *VERSION_PK_COLUMNS,
        sa.PrimaryKeyConstraint('ear_data_id', 'ear_id', 'transaction_id', name=op.f('pk_ear_data_targets_version')),
    )
    _add_version_indexes('ear_data_targets_version', ['ear_data_id', 'ear_id'])


def downgrade() -> None:
    new_version_tables = [
        'ear_data_targets_version',
        'animal_data_targets_version',
        'ear_data_version',
        'animal_data_version',
        'ear_data_type_version',
        'animal_data_type_version',
    ]
    new_tables = [
        'ear_data_targets',
        'animal_data_targets',
        'ear_data',
        'animal_data',
        'ear_data_type',
        'animal_data_type',
    ]
    for vt in new_version_tables:
        _drop_version_indexes(vt)
        op.drop_table(vt)
    for t in new_tables:
        op.drop_table(t)
