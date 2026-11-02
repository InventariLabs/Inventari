"""equipment: make the status agree with the assignments once.

Two counters described the same fact and disagreed: the dashboard tile counts
open assignments, while the asset list filters on
``meta_data -> 'equipment' ->> 'equipment_status'``. Nothing stopped the two
from drifting — a status set by hand raised one and not the other, and the
row that caused it was indistinguishable afterwards.

Every write path now refuses to create that drift (the batch action already
did; the item interceptor now covers the edit form and any plain item
update). This migration settles what earlier writes left behind, so the two
counters start from the same set of rows:

* ``DEPLOYED`` with nobody holding the asset becomes ``AVAILABLE``.
* ``AVAILABLE`` while an assignment is open becomes ``DEPLOYED``.

``MAINTENANCE`` and ``RETIRED`` are left alone in both directions: an asset
can legitimately be under repair while still assigned, and retiring closes
the assignment through its own path.

* Upgrade — rewrites the two disagreeing cases. Idempotent.
* Downgrade — no-op. The values it replaced were themselves the drift, and
  which of the two was "right" is not recoverable from the row.

Revision ID: 006_reconcile_equipment_status
Revises: 005_serial_number_to_column
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = '006_reconcile_equipment_status'
down_revision: str | None = '005_serial_number_to_column'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE items
        SET meta_data = jsonb_set(
            meta_data, '{equipment,equipment_status}', '"AVAILABLE"'
        )
        WHERE meta_data -> 'equipment' ->> 'equipment_status' = 'DEPLOYED'
          AND is_deleted = false
          AND NOT EXISTS (
              SELECT 1 FROM equipment_assignments a
              WHERE a.item_id = items.id
                AND a.organization_id = items.organization_id
                AND a.checked_in_at IS NULL
          )
        """
    )
    op.execute(
        """
        UPDATE items
        SET meta_data = jsonb_set(
            meta_data, '{equipment,equipment_status}', '"DEPLOYED"'
        )
        WHERE meta_data -> 'equipment' ->> 'equipment_status' = 'AVAILABLE'
          AND is_deleted = false
          AND EXISTS (
              SELECT 1 FROM equipment_assignments a
              WHERE a.item_id = items.id
                AND a.organization_id = items.organization_id
                AND a.checked_in_at IS NULL
          )
        """
    )


def downgrade() -> None:
    # The replaced values were the drift itself; restoring them would restore
    # the disagreement, not the truth.
    pass
