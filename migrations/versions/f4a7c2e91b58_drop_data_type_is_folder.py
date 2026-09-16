"""Drop data_type.is_folder

Whether sync walks directories or files is a property of the description
class, not an admin choice: only the class knows whether its parse()
expects a directory. It is now declared as DataTypeDescription.is_folder
and read through DataType.uses_folders, leaving this column with no
readers.

Keeping it was worse than dropping it. A stale column that disagrees with
the class fails silently: point a folder-based class at files and every
parse() returns None, so the sync reports success having ingested nothing.

Revision ID: f4a7c2e91b58
Revises: d2e4f6a8b1c3
Create Date: 2026-09-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f4a7c2e91b58'
down_revision: Union[str, None] = 'd2e4f6a8b1c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('data_type', 'is_folder')


def downgrade() -> None:
    op.add_column(
        'data_type',
        sa.Column('is_folder', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
    )
    # A rollback also reverts the code that reads the class, so the restored
    # column becomes authoritative again. Re-derive it from the registry
    # rather than leaving every folder-based DataType walking files -- the
    # exact silent failure this column was removed to prevent. Best effort:
    # the registry env var need not be set when migrations run.
    try:
        from colony_manager.datatypes import get_description_class_registry
        registry = get_description_class_registry()
    except Exception:
        return

    folder_keys = sorted(
        key for key, cls in registry.items()
        if getattr(cls, 'is_folder', False)
    )
    if not folder_keys:
        return

    op.get_bind().execute(
        sa.text(
            'UPDATE data_type SET is_folder = true '
            'WHERE description_class = ANY(:keys)'
        ),
        {'keys': folder_keys},
    )
