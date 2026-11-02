"""add level to storage_locations

Revision ID: storagelevel01
Revises: rsvdocline01
Create Date: 2026-08-15

Schema-only (ADR-014): adds the ``level`` column (NOT NULL, server default
'site' — the app always derives the real level from the parent; the default
only covers writes outside the app services). The backfill from tree depth
lives in storagelevel02. Keeping the backfill out of this file per AGENTS.md
("no data migrations in schema files").
"""

import sqlalchemy as sa
from alembic import op

revision = 'storagelevel01'
down_revision = 'rsvdocline01'
branch_labels = None
depends_on = None


def _run_upgrade_sql(bind) -> None:
    bind.execute(
        sa.text(
            "ALTER TABLE storage_locations "
            "ADD COLUMN level VARCHAR(20) NOT NULL DEFAULT 'site'"
        )
    )
    bind.execute(
        sa.text(
            'CREATE INDEX ix_storage_locations_level '
            'ON storage_locations (level)'
        )
    )


def _run_downgrade_sql(bind) -> None:
    bind.execute(sa.text('DROP INDEX IF EXISTS ix_storage_locations_level'))
    bind.execute(sa.text('ALTER TABLE storage_locations DROP COLUMN level'))


def upgrade() -> None:
    _run_upgrade_sql(op.get_bind())


def downgrade() -> None:
    _run_downgrade_sql(op.get_bind())
