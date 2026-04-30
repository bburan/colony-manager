"""Polymorphic DataType and Data

Drops the existing data, data_type, data_location, data_type_callback,
animal_data tables (and their _version shadows) and rebuilds them to
support joint-table inheritance keyed on a target_type discriminator.
Acceptable to lose existing rows since data is still in development.

Revision ID: 7f1c3a8d2e91
Revises: 3e1a2b3c4d5e
Create Date: 2026-04-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7f1c3a8d2e91'
down_revision: Union[str, Sequence[str], None] = '3e1a2b3c4d5e'
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


# Names of legacy tables we drop wholesale. Order matters for FK dependencies.
LEGACY_TABLES = [
    'animal_data',
    'data',
    'data_location',
    'data_type_callback',
    'data_type',
]
LEGACY_VERSION_TABLES = [
    'animal_data_version',
    'data_version',
    'data_location_version',
    'data_type_callback_version',
    'data_type_version',
]


def upgrade() -> None:
    # ----- Drop legacy schema -----
    for vt in LEGACY_VERSION_TABLES:
        _drop_version_indexes(vt)
        op.drop_table(vt)
    for t in LEGACY_TABLES:
        op.drop_table(t)

    # ----- data_type (polymorphic base) -----
    op.create_table(
        'data_type',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('target_type', sa.String(length=50), nullable=False),
        sa.Column('is_folder', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('parse_function', sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_data_type')),
        sa.UniqueConstraint('name', name=op.f('uq_data_type_name')),
    )
    op.create_table(
        'data_type_version',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('name', sa.String(length=100), autoincrement=False, nullable=True),
        sa.Column('description', sa.Text(), autoincrement=False, nullable=True),
        sa.Column('target_type', sa.String(length=50), autoincrement=False, nullable=True),
        sa.Column('is_folder', sa.Boolean(), server_default='false', autoincrement=False, nullable=True),
        sa.Column('parse_function', sa.String(length=200), autoincrement=False, nullable=True),
        *VERSION_PK_COLUMNS,
        sa.PrimaryKeyConstraint('id', 'transaction_id', name=op.f('pk_data_type_version')),
    )
    _add_version_indexes('data_type_version', ['id'])

    # ----- animal_event_data_type (subclass) -----
    op.create_table(
        'animal_event_data_type',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('default_procedure_id', sa.Integer(), nullable=True),
        sa.Column('default_procedure_target_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['id'], ['data_type.id'], name=op.f('fk_animal_event_data_type_id_data_type')),
        sa.ForeignKeyConstraint(['default_procedure_id'], ['animal_procedure.id'], name=op.f('fk_animal_event_data_type_default_procedure_id_animal_procedure')),
        sa.ForeignKeyConstraint(['default_procedure_target_id'], ['animal_procedure_target.id'], name=op.f('fk_animal_event_data_type_default_procedure_target_id_animal_procedure_target')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_animal_event_data_type')),
    )
    op.create_table(
        'animal_event_data_type_version',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('default_procedure_id', sa.Integer(), autoincrement=False, nullable=True),
        sa.Column('default_procedure_target_id', sa.Integer(), autoincrement=False, nullable=True),
        *VERSION_PK_COLUMNS,
        sa.PrimaryKeyConstraint('id', 'transaction_id', name=op.f('pk_animal_event_data_type_version')),
    )
    _add_version_indexes('animal_event_data_type_version', ['id'])

    # ----- confocal_image_data_type (subclass) -----
    op.create_table(
        'confocal_image_data_type',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['id'], ['data_type.id'], name=op.f('fk_confocal_image_data_type_id_data_type')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_confocal_image_data_type')),
    )
    op.create_table(
        'confocal_image_data_type_version',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
        *VERSION_PK_COLUMNS,
        sa.PrimaryKeyConstraint('id', 'transaction_id', name=op.f('pk_confocal_image_data_type_version')),
    )
    _add_version_indexes('confocal_image_data_type_version', ['id'])

    # ----- data_location -----
    op.create_table(
        'data_location',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('datatype_id', sa.Integer(), nullable=False),
        sa.Column('base_path', sa.String(length=1024), nullable=False),
        sa.ForeignKeyConstraint(['datatype_id'], ['data_type.id'], name=op.f('fk_data_location_datatype_id_data_type')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_data_location')),
    )
    op.create_table(
        'data_location_version',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('datatype_id', sa.Integer(), autoincrement=False, nullable=True),
        sa.Column('base_path', sa.String(length=1024), autoincrement=False, nullable=True),
        *VERSION_PK_COLUMNS,
        sa.PrimaryKeyConstraint('id', 'transaction_id', name=op.f('pk_data_location_version')),
    )
    _add_version_indexes('data_location_version', ['id'])

    # ----- data_type_callback -----
    op.create_table(
        'data_type_callback',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('datatype_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('callback_function', sa.String(length=200), nullable=False),
        sa.Column('callback_type', sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(['datatype_id'], ['data_type.id'], name=op.f('fk_data_type_callback_datatype_id_data_type')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_data_type_callback')),
    )
    op.create_table(
        'data_type_callback_version',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('datatype_id', sa.Integer(), autoincrement=False, nullable=True),
        sa.Column('name', sa.String(length=150), autoincrement=False, nullable=True),
        sa.Column('callback_function', sa.String(length=200), autoincrement=False, nullable=True),
        sa.Column('callback_type', sa.String(length=20), autoincrement=False, nullable=True),
        *VERSION_PK_COLUMNS,
        sa.PrimaryKeyConstraint('id', 'transaction_id', name=op.f('pk_data_type_callback_version')),
    )
    _add_version_indexes('data_type_callback_version', ['id'])

    # ----- data (polymorphic base) -----
    op.create_table(
        'data',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('datatype_id', sa.Integer(), nullable=False),
        sa.Column('location_id', sa.Integer(), nullable=False),
        sa.Column('target_type', sa.String(length=50), nullable=False),
        sa.Column('relative_path', sa.String(length=1024), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['datatype_id'], ['data_type.id'], name=op.f('fk_data_datatype_id_data_type')),
        sa.ForeignKeyConstraint(['location_id'], ['data_location.id'], name=op.f('fk_data_location_id_data_location')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_data')),
        sa.UniqueConstraint('location_id', 'relative_path', name=op.f('uq_data_location_id')),
    )
    op.create_table(
        'data_version',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('datatype_id', sa.Integer(), autoincrement=False, nullable=True),
        sa.Column('location_id', sa.Integer(), autoincrement=False, nullable=True),
        sa.Column('target_type', sa.String(length=50), autoincrement=False, nullable=True),
        sa.Column('relative_path', sa.String(length=1024), autoincrement=False, nullable=True),
        sa.Column('name', sa.String(length=255), autoincrement=False, nullable=True),
        sa.Column('date', sa.Date(), autoincrement=False, nullable=True),
        sa.Column('status', sa.String(length=50), autoincrement=False, nullable=True),
        sa.Column('notes', sa.Text(), autoincrement=False, nullable=True),
        *VERSION_PK_COLUMNS,
        sa.PrimaryKeyConstraint('id', 'transaction_id', name=op.f('pk_data_version')),
    )
    _add_version_indexes('data_version', ['id'])

    # ----- animal_event_data (subclass) -----
    op.create_table(
        'animal_event_data',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['id'], ['data.id'], name=op.f('fk_animal_event_data_id_data')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_animal_event_data')),
    )
    op.create_table(
        'animal_event_data_version',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
        *VERSION_PK_COLUMNS,
        sa.PrimaryKeyConstraint('id', 'transaction_id', name=op.f('pk_animal_event_data_version')),
    )
    _add_version_indexes('animal_event_data_version', ['id'])

    # ----- confocal_image_data (subclass) -----
    op.create_table(
        'confocal_image_data',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['id'], ['data.id'], name=op.f('fk_confocal_image_data_id_data')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_confocal_image_data')),
    )
    op.create_table(
        'confocal_image_data_version',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
        *VERSION_PK_COLUMNS,
        sa.PrimaryKeyConstraint('id', 'transaction_id', name=op.f('pk_confocal_image_data_version')),
    )
    _add_version_indexes('confocal_image_data_version', ['id'])

    # ----- M2M target tables -----
    op.create_table(
        'animal_event_data_targets',
        sa.Column('animal_event_data_id', sa.Integer(), nullable=False),
        sa.Column('animal_event_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['animal_event_data_id'], ['animal_event_data.id'], name=op.f('fk_animal_event_data_targets_animal_event_data_id_animal_event_data')),
        sa.ForeignKeyConstraint(['animal_event_id'], ['animal_event.id'], name=op.f('fk_animal_event_data_targets_animal_event_id_animal_event')),
        sa.PrimaryKeyConstraint('animal_event_data_id', 'animal_event_id', name=op.f('pk_animal_event_data_targets')),
    )
    op.create_table(
        'animal_event_data_targets_version',
        sa.Column('animal_event_data_id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('animal_event_id', sa.Integer(), autoincrement=False, nullable=False),
        *VERSION_PK_COLUMNS,
        sa.PrimaryKeyConstraint('animal_event_data_id', 'animal_event_id', 'transaction_id', name=op.f('pk_animal_event_data_targets_version')),
    )
    _add_version_indexes('animal_event_data_targets_version', ['animal_event_data_id', 'animal_event_id'])

    op.create_table(
        'confocal_image_data_targets',
        sa.Column('confocal_image_data_id', sa.Integer(), nullable=False),
        sa.Column('confocal_image_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['confocal_image_data_id'], ['confocal_image_data.id'], name=op.f('fk_confocal_image_data_targets_confocal_image_data_id_confocal_image_data')),
        sa.ForeignKeyConstraint(['confocal_image_id'], ['confocal_image.id'], name=op.f('fk_confocal_image_data_targets_confocal_image_id_confocal_image')),
        sa.PrimaryKeyConstraint('confocal_image_data_id', 'confocal_image_id', name=op.f('pk_confocal_image_data_targets')),
    )
    op.create_table(
        'confocal_image_data_targets_version',
        sa.Column('confocal_image_data_id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('confocal_image_id', sa.Integer(), autoincrement=False, nullable=False),
        *VERSION_PK_COLUMNS,
        sa.PrimaryKeyConstraint('confocal_image_data_id', 'confocal_image_id', 'transaction_id', name=op.f('pk_confocal_image_data_targets_version')),
    )
    _add_version_indexes('confocal_image_data_targets_version', ['confocal_image_data_id', 'confocal_image_id'])

    op.create_table(
        'data_candidate_animals',
        sa.Column('data_id', sa.Integer(), nullable=False),
        sa.Column('animal_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['animal_id'], ['animal.id'], name=op.f('fk_data_candidate_animals_animal_id_animal')),
        sa.ForeignKeyConstraint(['data_id'], ['data.id'], name=op.f('fk_data_candidate_animals_data_id_data')),
        sa.PrimaryKeyConstraint('data_id', 'animal_id', name=op.f('pk_data_candidate_animals')),
    )
    op.create_table(
        'data_candidate_animals_version',
        sa.Column('data_id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('animal_id', sa.Integer(), autoincrement=False, nullable=False),
        *VERSION_PK_COLUMNS,
        sa.PrimaryKeyConstraint('data_id', 'animal_id', 'transaction_id', name=op.f('pk_data_candidate_animals_version')),
    )
    _add_version_indexes('data_candidate_animals_version', ['data_id', 'animal_id'])


def downgrade() -> None:
    # Drop everything we created. No attempt to restore the previous shape;
    # this revision intentionally discards data.
    new_version_tables = [
        'data_candidate_animals_version',
        'confocal_image_data_targets_version',
        'animal_event_data_targets_version',
        'confocal_image_data_version',
        'animal_event_data_version',
        'data_version',
        'data_type_callback_version',
        'data_location_version',
        'confocal_image_data_type_version',
        'animal_event_data_type_version',
        'data_type_version',
    ]
    new_tables = [
        'data_candidate_animals',
        'confocal_image_data_targets',
        'animal_event_data_targets',
        'confocal_image_data',
        'animal_event_data',
        'data',
        'data_type_callback',
        'data_location',
        'confocal_image_data_type',
        'animal_event_data_type',
        'data_type',
    ]
    for vt in new_version_tables:
        _drop_version_indexes(vt)
        op.drop_table(vt)
    for t in new_tables:
        op.drop_table(t)
