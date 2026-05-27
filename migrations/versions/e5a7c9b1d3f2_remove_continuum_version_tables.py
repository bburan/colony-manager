"""Remove sqlalchemy_continuum version and transaction tables.

sqlalchemy_continuum is no longer a dependency. This migration drops
all ``*_version`` shadow tables and the ``transaction`` table that the
library created. The data they contain (change history) was never
surfaced in the application and is not recoverable after this point.

Revision ID: e5a7c9b1d3f2
Revises: d51a7b3c4e09
Create Date: 2026-05-27 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5a7c9b1d3f2'
down_revision: Union[str, Sequence[str], None] = 'd51a7b3c4e09'
branch_labels = None
depends_on = None

# All tables created by sqlalchemy_continuum across the migration history.
# Ordered so that M2M association version tables come before the row-level
# version tables they reference (though Postgres doesn't enforce this —
# the _version tables carry plain integer transaction_id columns, not FK
# constraints — the ordering is just for clarity).
_VERSION_TABLES = [
    # M2M association version tables
    'study_animals_version',
    'user_roles_version',
    'animal_event_tags_version',
    'animal_tags_version',
    'ear_tags_version',
    'animal_event_data_targets_version',
    'confocal_image_data_targets_version',
    'animal_data_targets_version',
    'ear_data_targets_version',
    'data_candidate_animals_version',
    'data_candidate_ears_version',
    # Per-row version history
    'animal_event_version',
    'animal_procedure_target_version',
    'animal_procedure_version',
    'animal_version',
    'breeding_pair_version',
    'cage_version',
    'confocal_image_type_version',
    'confocal_image_version',
    'ear_version',
    'immunolabeling_panel_version',
    'litter_version',
    'reagent_version',
    'source_version',
    'species_version',
    'study_version',
    'termination_reason_version',
    'user_role_version',
    'user_version',
    'feed_log_version',
    'feed_version',
    'weight_log_version',
    'data_location_version',
    'data_type_version',
    'data_version',
    'animal_event_data_version',
    'animal_event_data_type_version',
    'confocal_image_data_version',
    'confocal_image_data_type_version',
    'animal_data_version',
    'animal_data_type_version',
    'ear_data_version',
    'ear_data_type_version',
    'dosage_protocol_version',
    'dosage_protocol_drug_version',
    # Tag model version tables
    'animal_event_tag_version',
    'animal_tag_version',
    'ear_tag_version',
    # Created by 3e1a2b3c4d5e, then dropped by a1b2c3d4e5f6 — may not
    # exist in all environments; IF EXISTS handles that gracefully.
    'data_type_callback_version',
    # Continuum's audit header: one row per flushed transaction,
    # carries user_id + remote_addr.  Drop last because it has a FK
    # to ``user`` that Postgres would enforce on a normal DROP.
    'transaction',
]


def upgrade() -> None:
    for table in _VERSION_TABLES:
        op.execute(sa.text(f'DROP TABLE IF EXISTS "{table}"'))


def downgrade() -> None:
    raise NotImplementedError(
        "Removing sqlalchemy_continuum is irreversible via Alembic. "
        "Restore from a database backup if you need to revert."
    )
