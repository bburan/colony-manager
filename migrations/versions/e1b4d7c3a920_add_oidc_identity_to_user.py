"""Add OIDC identity columns to user

Links a local account to an external OpenID Connect identity so the same
row can be reached either by the local password form or by SSO. The pair
(issuer, subject) is the identity — ``sub`` is only promised to be unique
within an issuer — and is unique across accounts.

Revision ID: e1b4d7c3a920
Revises: f4a7c2e91b58
Create Date: 2026-09-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e1b4d7c3a920'
down_revision: Union[str, Sequence[str], None] = 'f4a7c2e91b58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user', sa.Column('oidc_issuer', sa.String(length=255), nullable=True))
    op.add_column('user', sa.Column('oidc_subject', sa.String(length=255), nullable=True))
    # Postgres treats NULLs as distinct in a unique constraint, so every
    # local-only account (both columns NULL) coexists under this happily.
    op.create_unique_constraint(
        'uq_user_oidc_identity', 'user', ['oidc_issuer', 'oidc_subject'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_user_oidc_identity', 'user', type_='unique')
    op.drop_column('user', 'oidc_subject')
    op.drop_column('user', 'oidc_issuer')
