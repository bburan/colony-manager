"""add dosage protocol

Revision ID: c4f8e1a92d50
Revises: b7c2a3f9e081
Create Date: 2026-05-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c4f8e1a92d50'
down_revision = 'b7c2a3f9e081'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'dosage_protocol',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('procedure_id', sa.Integer(), nullable=False),
        sa.Column('procedure_target_id', sa.Integer(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ['procedure_id'], ['animal_procedure.id'],
            name=op.f('fk_dosage_protocol_procedure_id_animal_procedure'),
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ['procedure_target_id'], ['animal_procedure_target.id'],
            name=op.f('fk_dosage_protocol_procedure_target_id_animal_procedure_target'),
            use_alter=True,
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_dosage_protocol')),
        sa.UniqueConstraint('name', name=op.f('uq_dosage_protocol_name')),
    )
    op.create_table(
        'dosage_protocol_version',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('name', sa.String(length=150), autoincrement=False, nullable=True),
        sa.Column('procedure_id', sa.Integer(), autoincrement=False, nullable=True),
        sa.Column('procedure_target_id', sa.Integer(), autoincrement=False, nullable=True),
        sa.Column('notes', sa.Text(), autoincrement=False, nullable=True),
        sa.Column('transaction_id', sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column('end_transaction_id', sa.BigInteger(), nullable=True),
        sa.Column('operation_type', sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint('id', 'transaction_id', name=op.f('pk_dosage_protocol_version')),
    )
    with op.batch_alter_table('dosage_protocol_version', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_dosage_protocol_version_end_transaction_id'), ['end_transaction_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dosage_protocol_version_operation_type'), ['operation_type'], unique=False)
        batch_op.create_index('ix_dosage_protocol_version_pk_transaction_id', ['id', sa.literal_column('transaction_id DESC')], unique=False)
        batch_op.create_index('ix_dosage_protocol_version_pk_validity', ['id', 'transaction_id', 'end_transaction_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dosage_protocol_version_transaction_id'), ['transaction_id'], unique=False)

    op.create_table(
        'dosage_protocol_drug',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('protocol_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('dose_mg_per_kg', sa.Float(), nullable=False),
        sa.Column('concentration_mg_per_ml', sa.Float(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ['protocol_id'], ['dosage_protocol.id'],
            name=op.f('fk_dosage_protocol_drug_protocol_id_dosage_protocol'),
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_dosage_protocol_drug')),
    )
    op.create_table(
        'dosage_protocol_drug_version',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('protocol_id', sa.Integer(), autoincrement=False, nullable=True),
        sa.Column('name', sa.String(length=100), autoincrement=False, nullable=True),
        sa.Column('dose_mg_per_kg', sa.Float(), autoincrement=False, nullable=True),
        sa.Column('concentration_mg_per_ml', sa.Float(), autoincrement=False, nullable=True),
        sa.Column('position', sa.Integer(), autoincrement=False, nullable=True),
        sa.Column('transaction_id', sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column('end_transaction_id', sa.BigInteger(), nullable=True),
        sa.Column('operation_type', sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint('id', 'transaction_id', name=op.f('pk_dosage_protocol_drug_version')),
    )
    with op.batch_alter_table('dosage_protocol_drug_version', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_dosage_protocol_drug_version_end_transaction_id'), ['end_transaction_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dosage_protocol_drug_version_operation_type'), ['operation_type'], unique=False)
        batch_op.create_index('ix_dosage_protocol_drug_version_pk_transaction_id', ['id', sa.literal_column('transaction_id DESC')], unique=False)
        batch_op.create_index('ix_dosage_protocol_drug_version_pk_validity', ['id', 'transaction_id', 'end_transaction_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dosage_protocol_drug_version_transaction_id'), ['transaction_id'], unique=False)


def downgrade():
    with op.batch_alter_table('dosage_protocol_drug_version', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_dosage_protocol_drug_version_transaction_id'))
        batch_op.drop_index('ix_dosage_protocol_drug_version_pk_validity')
        batch_op.drop_index('ix_dosage_protocol_drug_version_pk_transaction_id')
        batch_op.drop_index(batch_op.f('ix_dosage_protocol_drug_version_operation_type'))
        batch_op.drop_index(batch_op.f('ix_dosage_protocol_drug_version_end_transaction_id'))
    op.drop_table('dosage_protocol_drug_version')
    op.drop_table('dosage_protocol_drug')

    with op.batch_alter_table('dosage_protocol_version', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_dosage_protocol_version_transaction_id'))
        batch_op.drop_index('ix_dosage_protocol_version_pk_validity')
        batch_op.drop_index('ix_dosage_protocol_version_pk_transaction_id')
        batch_op.drop_index(batch_op.f('ix_dosage_protocol_version_operation_type'))
        batch_op.drop_index(batch_op.f('ix_dosage_protocol_version_end_transaction_id'))
    op.drop_table('dosage_protocol_version')
    op.drop_table('dosage_protocol')
