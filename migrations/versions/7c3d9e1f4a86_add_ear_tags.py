"""add ear tags

Revision ID: 7c3d9e1f4a86
Revises: 5e8a1b2c3d40
Create Date: 2026-05-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7c3d9e1f4a86'
down_revision = '5e8a1b2c3d40'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ear_tag',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['parent_id'], ['ear_tag.id'], name=op.f('fk_ear_tag_parent_id_ear_tag')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ear_tag')),
        sa.UniqueConstraint('name', name=op.f('uq_ear_tag_name')),
    )
    op.create_table('ear_tag_version',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('name', sa.String(length=150), autoincrement=False, nullable=True),
        sa.Column('parent_id', sa.Integer(), autoincrement=False, nullable=True),
        sa.Column('transaction_id', sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column('end_transaction_id', sa.BigInteger(), nullable=True),
        sa.Column('operation_type', sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint('id', 'transaction_id', name=op.f('pk_ear_tag_version')),
    )
    with op.batch_alter_table('ear_tag_version', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ear_tag_version_end_transaction_id'), ['end_transaction_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ear_tag_version_operation_type'), ['operation_type'], unique=False)
        batch_op.create_index('ix_ear_tag_version_pk_transaction_id', ['id', sa.literal_column('transaction_id DESC')], unique=False)
        batch_op.create_index('ix_ear_tag_version_pk_validity', ['id', 'transaction_id', 'end_transaction_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ear_tag_version_transaction_id'), ['transaction_id'], unique=False)

    op.create_table('ear_tags',
        sa.Column('ear_id', sa.Integer(), nullable=False),
        sa.Column('tag_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['ear_id'], ['ear.id'], name=op.f('fk_ear_tags_ear_id_ear')),
        sa.ForeignKeyConstraint(['tag_id'], ['ear_tag.id'], name=op.f('fk_ear_tags_tag_id_ear_tag')),
        sa.PrimaryKeyConstraint('ear_id', 'tag_id', name=op.f('pk_ear_tags')),
    )
    op.create_table('ear_tags_version',
        sa.Column('ear_id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('tag_id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('transaction_id', sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column('end_transaction_id', sa.BigInteger(), nullable=True),
        sa.Column('operation_type', sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint('ear_id', 'tag_id', 'transaction_id', name=op.f('pk_ear_tags_version')),
    )
    with op.batch_alter_table('ear_tags_version', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ear_tags_version_end_transaction_id'), ['end_transaction_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ear_tags_version_operation_type'), ['operation_type'], unique=False)
        batch_op.create_index('ix_ear_tags_version_pk_transaction_id', ['ear_id', 'tag_id', sa.literal_column('transaction_id DESC')], unique=False)
        batch_op.create_index('ix_ear_tags_version_pk_validity', ['ear_id', 'tag_id', 'transaction_id', 'end_transaction_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ear_tags_version_transaction_id'), ['transaction_id'], unique=False)


def downgrade():
    op.drop_table('ear_tags')
    with op.batch_alter_table('ear_tags_version', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ear_tags_version_transaction_id'))
        batch_op.drop_index('ix_ear_tags_version_pk_validity')
        batch_op.drop_index('ix_ear_tags_version_pk_transaction_id')
        batch_op.drop_index(batch_op.f('ix_ear_tags_version_operation_type'))
        batch_op.drop_index(batch_op.f('ix_ear_tags_version_end_transaction_id'))
    op.drop_table('ear_tags_version')

    with op.batch_alter_table('ear_tag_version', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ear_tag_version_transaction_id'))
        batch_op.drop_index('ix_ear_tag_version_pk_validity')
        batch_op.drop_index('ix_ear_tag_version_pk_transaction_id')
        batch_op.drop_index(batch_op.f('ix_ear_tag_version_operation_type'))
        batch_op.drop_index(batch_op.f('ix_ear_tag_version_end_transaction_id'))
    op.drop_table('ear_tag_version')
    op.drop_table('ear_tag')
