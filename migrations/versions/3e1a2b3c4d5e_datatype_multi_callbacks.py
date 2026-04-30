"""DataType multi-callbacks

Revision ID: 3e1a2b3c4d5e
Revises: dcf6955e7e8c
Create Date: 2026-04-29 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column


# revision identifiers, used by Alembic.
revision: str = '3e1a2b3c4d5e'
down_revision: Union[str, Sequence[str], None] = 'dcf6955e7e8c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create data_type_callback table
    op.create_table('data_type_callback',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('datatype_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('callback_function', sa.String(length=200), nullable=False),
        sa.Column('callback_type', sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(['datatype_id'], ['data_type.id'], name=op.f('fk_data_type_callback_datatype_id_data_type')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_data_type_callback'))
    )

    # 2. Create data_type_callback_version table
    op.create_table('data_type_callback_version',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('datatype_id', sa.Integer(), autoincrement=False, nullable=True),
        sa.Column('name', sa.String(length=150), autoincrement=False, nullable=True),
        sa.Column('callback_function', sa.String(length=200), autoincrement=False, nullable=True),
        sa.Column('callback_type', sa.String(length=20), autoincrement=False, nullable=True),
        sa.Column('transaction_id', sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column('end_transaction_id', sa.BigInteger(), nullable=True),
        sa.Column('operation_type', sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint('id', 'transaction_id', name=op.f('pk_data_type_callback_version'))
    )
    op.create_index(op.f('ix_data_type_callback_version_end_transaction_id'), 'data_type_callback_version', ['end_transaction_id'], unique=False)
    op.create_index(op.f('ix_data_type_callback_version_operation_type'), 'data_type_callback_version', ['operation_type'], unique=False)
    op.create_index('ix_data_type_callback_version_pk_transaction_id', 'data_type_callback_version', ['id', sa.literal_column('transaction_id DESC')], unique=False)
    op.create_index('ix_data_type_callback_version_pk_validity', 'data_type_callback_version', ['id', 'transaction_id', 'end_transaction_id'], unique=False)
    op.create_index(op.f('ix_data_type_callback_version_transaction_id'), 'data_type_callback_version', ['transaction_id'], unique=False)

    # 3. Data Migration
    data_type_table = table('data_type',
        column('id', sa.Integer),
        column('loader_function', sa.String),
        column('pdf_generator_function', sa.String)
    )
    
    # We need to use connection for data migration
    conn = op.get_bind()
    
    # Fetch existing data types
    res = conn.execute(sa.select(data_type_table.c.id, data_type_table.c.loader_function, data_type_table.c.pdf_generator_function))
    
    data_type_callback_table = table('data_type_callback',
        column('datatype_id', sa.Integer),
        column('name', sa.String),
        column('callback_function', sa.String),
        column('callback_type', sa.String)
    )
    
    for dt_id, loader, pdf in res:
        if loader:
            name = loader.split('.')[-1].replace('_', ' ').capitalize()
            conn.execute(data_type_callback_table.insert().values(
                datatype_id=dt_id,
                name=name,
                callback_function=loader,
                callback_type='plot'
            ))
        if pdf:
            name = pdf.split('.')[-1].replace('_', ' ').capitalize()
            conn.execute(data_type_callback_table.insert().values(
                datatype_id=dt_id,
                name=name,
                callback_function=pdf,
                callback_type='pdf'
            ))

    # 4. Drop legacy columns
    op.drop_column('data_type', 'loader_function')
    op.drop_column('data_type', 'pdf_generator_function')
    op.drop_column('data_type_version', 'loader_function')
    op.drop_column('data_type_version', 'pdf_generator_function')


def downgrade() -> None:
    # Add columns back
    op.add_column('data_type_version', sa.Column('pdf_generator_function', sa.String(length=200), autoincrement=False, nullable=True))
    op.add_column('data_type_version', sa.Column('loader_function', sa.String(length=200), autoincrement=False, nullable=True))
    op.add_column('data_type', sa.Column('pdf_generator_function', sa.String(length=200), nullable=True))
    op.add_column('data_type', sa.Column('loader_function', sa.String(length=200), nullable=True))

    # Reverse data migration (optional, might be complex if there are multiple callbacks)
    # For now, just drop the tables
    op.drop_index(op.f('ix_data_type_callback_version_transaction_id'), table_name='data_type_callback_version')
    op.drop_index('ix_data_type_callback_version_pk_validity', table_name='data_type_callback_version')
    op.drop_index('ix_data_type_callback_version_pk_transaction_id', table_name='data_type_callback_version')
    op.drop_index(op.f('ix_data_type_callback_version_operation_type'), table_name='data_type_callback_version')
    op.drop_index(op.f('ix_data_type_callback_version_end_transaction_id'), table_name='data_type_callback_version')
    op.drop_table('data_type_callback_version')
    op.drop_table('data_type_callback')
