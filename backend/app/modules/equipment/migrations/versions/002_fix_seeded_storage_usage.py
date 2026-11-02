"""equipment: repair on_enable-seeded storage_locations.usage from 'active' to 'internal'.

The equipment module's ``on_enable()`` seeded the default storage locations
(``Server Room``, ``IT Storage``) with ``usage='active'``. That value is NOT
in the ``LocationUsage`` enum (``internal``, ``customer``, ``inventory``,
``production``, ``supplier``, ``transit``, ``scrap``). The ``usage`` column
is a plain ``String(50)`` with no DB-level enum, so the invalid value was
silently accepted on insert. Downstream, ``GET /storages`` and
``GET /storages/tree`` default ``usage='internal'`` and therefore hid those
seeded rows from the UI.

This data-only migration:

* Upgrade — rewrites ``usage='active'`` to ``usage='internal'`` for every
  row with ``context_tag='equipment'``. Idempotent: re-running is a no-op
  because the WHERE clause filters on the legacy value.
* Downgrade — rewrites ``usage='internal'`` back to ``usage='active'`` ONLY
  for the two seed names (``Server Room``, ``IT Storage``) so we don't
  accidentally stomp on user-created equipment rows that we are not
  confident were seeded by this module. Pre-existing ``internal`` rows with
  other names are left untouched.

Revision ID: 002_fix_seeded_storage_usage
Revises: 001_initial
Create Date: 2026-07-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '002_fix_seeded_storage_usage'
down_revision: str | None = '001_initial'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Repair legacy ``usage='active'`` rows tagged as equipment storage."""
    op.execute(
        sa.text(
            """
            UPDATE storage_locations
            SET usage = 'internal'
            WHERE usage = 'active'
              AND context_tag = 'equipment'
            """
        )
    )


def downgrade() -> None:
    """Best-effort restoration: rewrite seed names back to ``'active'``.

    Scoped to ``context_tag='equipment'`` AND the two known seed names so
    user-created equipment rows are not affected by the downgrade.
    """
    op.execute(
        sa.text(
            """
            UPDATE storage_locations
            SET usage = 'active'
            WHERE context_tag = 'equipment'
              AND usage = 'internal'
              AND name IN ('Server Room', 'IT Storage')
            """
        )
    )
