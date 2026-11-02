"""equipment: move the asset serial number into the core column.

An asset was identified by a number the application wrote in two places
depending on the door it came through: the batch path filled
``items.serial_number``, while the single form and the import wrote only
``meta_data -> 'equipment' ->> 'serial_number'``. Two assets created two
ways carried their number in two different places, and the core search —
the one the command palette asks — read neither.

The column is now the single home. This migration moves what the namespace
holds into it and takes the namespace copy away, so a later edit cannot
leave the two disagreeing.

``uq_items_org_serial`` makes the column unique per organization among live
rows, and nothing enforced that on the namespace. A number the namespace
repeats is therefore **left where it is**: the row keeps its number in
``meta_data`` (the module reads both places) instead of the migration
failing or one asset silently losing its identifier. Those rows surface as
duplicates for a human to resolve, which is the honest outcome.

Archived rows are left alone for the same reason: the unique index ignores
them, so moving their number could hand a restored asset a number a live
one already holds. Their number stays readable through the namespace.

* Upgrade — fills an empty ``items.serial_number`` from the namespace where
  the value is unambiguous, then drops the namespace copy on the rows where
  the two now agree. Idempotent.
* Downgrade — writes the column back into the namespace for equipment rows,
  leaving the column in place (other verticals may rely on it).

Revision ID: 005_serial_number_to_column
Revises: 004_audit_response_items
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = '005_serial_number_to_column'
down_revision: str | None = '004_audit_response_items'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        WITH candidates AS (
            SELECT
                id,
                organization_id,
                meta_data -> 'equipment' ->> 'serial_number' AS sn
            FROM items
            WHERE is_deleted = false
              AND (serial_number IS NULL OR serial_number = '')
              AND nullif(meta_data -> 'equipment' ->> 'serial_number', '')
                  IS NOT NULL
        ),
        movable AS (
            SELECT c.id, c.sn
            FROM candidates c
            WHERE (
                SELECT count(*) FROM candidates d
                WHERE d.organization_id = c.organization_id AND d.sn = c.sn
            ) = 1
            AND NOT EXISTS (
                SELECT 1 FROM items o
                WHERE o.organization_id = c.organization_id
                  AND o.is_deleted = false
                  AND o.serial_number = c.sn
            )
        )
        UPDATE items i
        SET serial_number = m.sn
        FROM movable m
        WHERE i.id = m.id
        """
    )
    op.execute(
        """
        UPDATE items
        SET meta_data = jsonb_set(
            meta_data,
            '{equipment}',
            (meta_data -> 'equipment') - 'serial_number'
        )
        WHERE meta_data -> 'equipment' ? 'serial_number'
          AND serial_number IS NOT NULL
          AND serial_number = meta_data -> 'equipment' ->> 'serial_number'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE items
        SET meta_data = jsonb_set(
            meta_data,
            '{equipment}',
            (meta_data -> 'equipment')
                || jsonb_build_object('serial_number', serial_number)
        )
        WHERE serial_number IS NOT NULL
          AND serial_number <> ''
          AND meta_data ? 'equipment'
        """
    )
