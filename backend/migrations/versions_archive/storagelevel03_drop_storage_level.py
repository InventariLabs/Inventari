"""drop level from storage_locations

Revision ID: storagelevel03
Revises: svlcst22
Create Date: 2026-08-30

Schema-only (ADR-018): the location tree has no ceiling and no named levels,
so a node's position is described by ``parent_id`` alone. Nothing needs a
backfill — 3 → N is a loosening and every existing row stays valid.

``downgrade`` re-creates the column and its index, but not the values: a tree
that has grown deeper than three levels since the drop has no correct level
to be given, and the column is NOT NULL, so every row lands on the original
``'site'`` default. Two consequences worth knowing before going backwards:

- the levels are wrong until something rewrites them, and nothing does;
- ``storagelevel02_backfill_storage_levels`` aborts loudly on any node
  deeper than the third level, so downgrading *past* this revision on such a
  tree and coming back up stops there. Downgrade to this revision, never
  below it.
"""

import sqlalchemy as sa
from alembic import op

revision = 'storagelevel03'
down_revision = 'svlcst22'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text('DROP INDEX IF EXISTS ix_storage_locations_level'))
    bind.execute(
        sa.text('ALTER TABLE storage_locations DROP COLUMN IF EXISTS level')
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            'ALTER TABLE storage_locations '
            "ADD COLUMN IF NOT EXISTS level VARCHAR(20) NOT NULL DEFAULT 'site'"
        )
    )
    bind.execute(
        sa.text(
            'CREATE INDEX IF NOT EXISTS ix_storage_locations_level '
            'ON storage_locations (level)'
        )
    )
