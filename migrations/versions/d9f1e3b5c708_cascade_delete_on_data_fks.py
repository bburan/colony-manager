"""Add ON DELETE CASCADE to data-related foreign keys.

Lets bulk-delete patterns work end-to-end:

* Deleting a ``Data`` row (parent of joint-table inheritance) cascades to
  its joint-inheritance child row (``animal_event_data``,
  ``confocal_image_data``, ``animal_data``, ``ear_data``).
* Deleting any ``Data`` row (parent or subclass) cascades to its M2M
  secondary rows (``*_targets`` and ``data_candidate_animals``).
* Deleting the side that the M2M points at (e.g. an ``AnimalEvent`` or
  ``ConfocalImage``) also cleans up the M2M rows.

Revision ID: d9f1e3b5c708
Revises: c7d9e1b3a205
Create Date: 2026-05-05 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd9f1e3b5c708'
down_revision: Union[str, Sequence[str], None] = 'c7d9e1b3a205'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _fks():
    """Yield (table, column, ref_table, ref_column, name) for every FK we alter.

    Names are passed through ``op.f()`` so the same identifier-truncation rule
    that produced the existing constraint name is applied here.
    """
    return [
        # M2M target tables → Data subclasses
        ('confocal_image_data_targets', 'confocal_image_data_id',
         'confocal_image_data', 'id',
         op.f('fk_confocal_image_data_targets_confocal_image_data_id_confocal_image_data')),
        ('animal_event_data_targets', 'animal_event_data_id',
         'animal_event_data', 'id',
         op.f('fk_animal_event_data_targets_animal_event_data_id_animal_event_data')),
        ('animal_data_targets', 'animal_data_id',
         'animal_data', 'id',
         op.f('fk_animal_data_targets_animal_data_id_animal_data')),
        ('ear_data_targets', 'ear_data_id',
         'ear_data', 'id',
         op.f('fk_ear_data_targets_ear_data_id_ear_data')),

        # M2M target tables → real-world entities
        ('confocal_image_data_targets', 'confocal_image_id',
         'confocal_image', 'id',
         op.f('fk_confocal_image_data_targets_confocal_image_id_confocal_image')),
        ('animal_event_data_targets', 'animal_event_id',
         'animal_event', 'id',
         op.f('fk_animal_event_data_targets_animal_event_id_animal_event')),
        ('animal_data_targets', 'animal_id',
         'animal', 'id',
         op.f('fk_animal_data_targets_animal_id_animal')),
        ('ear_data_targets', 'ear_id',
         'ear', 'id',
         op.f('fk_ear_data_targets_ear_id_ear')),

        # data_candidate_animals
        ('data_candidate_animals', 'data_id', 'data', 'id',
         op.f('fk_data_candidate_animals_data_id_data')),
        ('data_candidate_animals', 'animal_id', 'animal', 'id',
         op.f('fk_data_candidate_animals_animal_id_animal')),

        # Joint-inheritance child → parent
        ('animal_event_data', 'id', 'data', 'id',
         op.f('fk_animal_event_data_id_data')),
        ('confocal_image_data', 'id', 'data', 'id',
         op.f('fk_confocal_image_data_id_data')),
        ('animal_data', 'id', 'data', 'id',
         op.f('fk_animal_data_id_data')),
        ('ear_data', 'id', 'data', 'id',
         op.f('fk_ear_data_id_data')),
    ]


def upgrade() -> None:
    for table, col, ref_table, ref_col, name in _fks():
        op.drop_constraint(name, table, type_='foreignkey')
        op.create_foreign_key(
            name, table, ref_table, [col], [ref_col],
            ondelete='CASCADE',
        )


def downgrade() -> None:
    for table, col, ref_table, ref_col, name in _fks():
        op.drop_constraint(name, table, type_='foreignkey')
        op.create_foreign_key(
            name, table, ref_table, [col], [ref_col],
        )
