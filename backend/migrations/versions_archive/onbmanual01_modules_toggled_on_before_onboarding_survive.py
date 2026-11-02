"""modules toggled on by hand before onboarding survive the profile answer.

Revision ID: onbmanual01
Revises: pgszorg01
Create Date: 2026-10-04

``pre_onboarding_manual_modules`` records the modules an administrator
switched on (or back off) through POST /modules/toggle while the
organization's onboarding still stood open. Completing onboarding used to
overwrite ``enabled_modules`` with the chosen profile's set, so an explicit
choice the profile does not offer was dropped without its disable hook and
without a word to the admin.

The column is nullable with no default that rewrites existing rows: every
organization that never toggled by hand reads NULL and behaves exactly as
before, and onboarded organizations never write it again — the setup
endpoint refuses a second run and the record is consumed by the first.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'onbmanual01'
down_revision: str | None = 'pgszorg01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'organizations',
        sa.Column('pre_onboarding_manual_modules', sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('organizations', 'pre_onboarding_manual_modules')
