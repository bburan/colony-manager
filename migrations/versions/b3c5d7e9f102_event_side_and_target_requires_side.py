"""Add AnimalEvent.side and AnimalProcedureTarget.requires_side.

Side is a property of the event, not the target — bilateral procedures are
modeled as two events. The target carries a ``requires_side`` flag so the
event form knows whether to show the side selector.

Revision ID: b3c5d7e9f102
Revises: 9a4b1c5e7f02
Create Date: 2026-05-05 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3c5d7e9f102'
down_revision: Union[str, Sequence[str], None] = '9a4b1c5e7f02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('animal_event', sa.Column('side', sa.String(length=10), nullable=True))
    op.add_column('animal_event_version', sa.Column('side', sa.String(length=10), autoincrement=False, nullable=True))

    op.add_column('animal_procedure_target', sa.Column('requires_side', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('animal_procedure_target_version', sa.Column('requires_side', sa.Boolean(), autoincrement=False, nullable=True))


def downgrade() -> None:
    op.drop_column('animal_procedure_target_version', 'requires_side')
    op.drop_column('animal_procedure_target', 'requires_side')

    op.drop_column('animal_event_version', 'side')
    op.drop_column('animal_event', 'side')
