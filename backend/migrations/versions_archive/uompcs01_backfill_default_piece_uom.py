"""backfill items.uom_id with the system piece unit

Revision ID: uompcs01
Revises: uomlabel01
Create Date: 2026-08-30

A product without a unit made the quantity column unreadable
— 82% of rows in the audited database carried no unit, so "10" could have been
grams, litres or pieces. The column now says "—" for such a row, which shows the
gap without closing it. The service now defaults a unitless create to pieces; this
migration gives the rows that predate the default the same answer.

The system ``pcs`` row (``organization_id IS NULL``, ``is_system``) is the
default for every tenant: a piece is the neutral counted unit (Odoo's Units,
ERPNext's Nos). Orgs keep their own rows untouched — only NULL is rewritten.

One direction only: afterwards a defaulted row and a row where someone chose
pieces are indistinguishable, so ``downgrade`` is a documented no-op (same
contract as ``011_backfill_order_numbers``).
"""

from alembic import op

revision = 'uompcs01'
down_revision = 'uomlabel01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE items
           SET uom_id = (
               SELECT id FROM uoms
                WHERE symbol = 'pcs'
                  AND organization_id IS NULL
                LIMIT 1
           )
         WHERE uom_id IS NULL
        """
    )


def downgrade() -> None:
    # A defaulted row and a deliberately-pieces row are indistinguishable;
    # un-setting both would destroy a choice. No-op, by design.
    pass
