"""unique (org, year, month) on inventory_periods.

Revision ID: doc_inv_period_uq01
Revises: doc_putaway_rules01
Create Date: 2026-07-24

Previously uniqueness of an inventory period relied solely on an application-
level advisory lock. A race, a bypassed code path, or manual DB edits could
create duplicate closure rows for the same (organization, year, month). This
adds a hard UNIQUE constraint.

The constraint is added defensively: any pre-existing duplicates are collapsed
first (keeping the most recently closed row per (org, year, month)), so the
migration never fails on dirty data.
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'doc_inv_period_uq01'
down_revision: str | None = 'doc_putaway_rules01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Collapse duplicates before adding the constraint: keep the row with the
    # latest closed_at (NULLS LAST), delete the rest. Idempotent on clean data.
    op.execute(
        """
        DELETE FROM inventory_periods ip
        USING inventory_periods ip_keep
        WHERE ip.organization_id = ip_keep.organization_id
          AND ip.year = ip_keep.year
          AND ip.month = ip_keep.month
          AND ip.id <> ip_keep.id
          AND COALESCE(ip.closed_at, '-infinity'::timestamptz)
              <= COALESCE(ip_keep.closed_at, '-infinity'::timestamptz)
        """
    )
    op.create_unique_constraint(
        'uq_inventory_period_org_year_month',
        'inventory_periods',
        ['organization_id', 'year', 'month'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'uq_inventory_period_org_year_month', 'inventory_periods', type_='unique'
    )
