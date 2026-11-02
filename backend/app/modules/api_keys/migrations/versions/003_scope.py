"""add the scope column to api_keys.

A key issued for one job — a print agent next to the printer — names its scope
here and reaches only the paths that scope's module registered. NULL keeps a key
what every key was before: an ordinary one.

Revision ID: 003_scope
Revises: 002_drop_scopes
Create Date: 2026-10-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '003_scope'
down_revision: str | None = '002_drop_scopes'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `IF NOT EXISTS`, for the reason 002 drops with `IF EXISTS`: an
    # installation whose table came from current metadata already has the
    # column, and `db upgrade-modules` stamps it at 001_initial and replays
    # from there. The post-condition is the same either way.
    op.execute(
        sa.text('ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS scope VARCHAR(32)')
    )


def downgrade() -> None:
    op.drop_column('api_keys', 'scope')
