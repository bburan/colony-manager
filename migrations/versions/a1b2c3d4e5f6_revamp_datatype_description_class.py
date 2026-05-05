"""Revamp DataType: description_class, file_hash, drop callbacks.

- Rename ``data_type.parse_function`` → ``data_type.description_class``
- Add ``data.file_hash`` column (VARCHAR(64), nullable)
- Drop ``data_type_callback`` table and its version shadow table

Revision ID: a1b2c3d4e5f6
Revises: b3c5d7e9f102
Create Date: 2026-05-05 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'b3c5d7e9f102'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Rename parse_function → description_class on data_type
    with op.batch_alter_table('data_type') as batch_op:
        batch_op.alter_column(
            'parse_function',
            new_column_name='description_class',
            existing_type=sa.String(200),
            existing_nullable=True,
        )

    # Also update the version shadow table if it exists
    try:
        with op.batch_alter_table('data_type_version') as batch_op:
            batch_op.alter_column(
                'parse_function',
                new_column_name='description_class',
                existing_type=sa.String(200),
                existing_nullable=True,
            )
    except Exception:
        pass  # Version table may not exist in all environments

    # 2. Add file_hash column to data
    with op.batch_alter_table('data') as batch_op:
        batch_op.add_column(
            sa.Column('file_hash', sa.String(64), nullable=True)
        )

    # Also update the version shadow table
    try:
        with op.batch_alter_table('data_version') as batch_op:
            batch_op.add_column(
                sa.Column('file_hash', sa.String(64), nullable=True)
            )
    except Exception:
        pass

    # 3. Drop data_type_callback version table first (FK ordering)
    try:
        op.drop_table('data_type_callback_version')
    except Exception:
        pass

    # 4. Drop data_type_callback table
    op.drop_table('data_type_callback')


def downgrade() -> None:
    # 1. Re-create data_type_callback table
    op.create_table(
        'data_type_callback',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('datatype_id', sa.Integer(), sa.ForeignKey('data_type.id'), nullable=False),
        sa.Column('name', sa.String(150), nullable=False),
        sa.Column('callback_function', sa.String(200), nullable=False),
        sa.Column('callback_type', sa.String(20), nullable=False),
    )

    # 2. Drop file_hash from data
    with op.batch_alter_table('data') as batch_op:
        batch_op.drop_column('file_hash')

    try:
        with op.batch_alter_table('data_version') as batch_op:
            batch_op.drop_column('file_hash')
    except Exception:
        pass

    # 3. Rename description_class → parse_function
    with op.batch_alter_table('data_type') as batch_op:
        batch_op.alter_column(
            'description_class',
            new_column_name='parse_function',
            existing_type=sa.String(200),
            existing_nullable=True,
        )

    try:
        with op.batch_alter_table('data_type_version') as batch_op:
            batch_op.alter_column(
                'description_class',
                new_column_name='parse_function',
                existing_type=sa.String(200),
                existing_nullable=True,
            )
    except Exception:
        pass
