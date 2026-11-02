"""the pick line names the group and the lot, not only the quant

Revision ID: doc_pick_group01
Revises: doc_country_law01
Create Date: 2026-09-27

A picking line was planned from a row of the quant table: ``quant_id``
carried the shelf's stock row, and everything the line knew about where
and from which batch came back through it. The quant table is going away,
and a line that can only point at it would lose its shelf and
its batch with it.

Two columns join ``quant_id`` instead of replacing it: ``anchor_id`` is
the group the line plans from — the ``stock_anchors`` row one per
(organization, product, shelf) — and ``lot_id`` is the batch the picker
is to take. Both are nullable, because a line planned against a shelf
nothing has stocked has no group row to name, and stock without a batch
has no lot; such a line keeps answering the scan key it always answered.

The backfill reads the group through the quant each existing line still
names, so lines planned before this migration carry the same group and
lot the planning code writes from now on. A line whose quant points at a
group no anchor row covers (a database that grew before anchors were
backfilled) stays NULL in ``anchor_id`` rather than failing the upgrade —
the same answer the planning code gives for an unstocked shelf.

Downgrade drops both columns, and the quant each line still names keeps
the line working exactly as it did before.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.migration_helpers import relation_exists

revision: str = 'doc_pick_group01'
down_revision: str | Sequence[str] | None = 'doc_country_law01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The line's group comes from the quant it already names: the anchor is
#: the row of (organization, product, shelf) and the lot is the quant's.
_BACKFILL = """
    UPDATE wms_pick_lines AS pl
       SET anchor_id = a.id,
           lot_id = q.lot_id
      FROM stock_quants AS q
      JOIN stock_anchors AS a
        ON a.organization_id = q.organization_id
       AND a.product_template_id = q.product_template_id
       AND a.storage_location_id = q.storage_location_id
     WHERE pl.quant_id = q.id
       AND pl.anchor_id IS NULL
"""


def upgrade() -> None:
    op.add_column('wms_pick_lines', sa.Column('anchor_id', sa.Uuid(), nullable=True))
    op.add_column('wms_pick_lines', sa.Column('lot_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_wms_pick_lines_anchor_id',
        'wms_pick_lines',
        'stock_anchors',
        ['anchor_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_wms_pick_lines_lot_id',
        'wms_pick_lines',
        'stock_lots',
        ['lot_id'],
        ['id'],
        ondelete='SET NULL',
    )
    # A core built after the quant table went (``quantdrop01``) has no lines
    # planned from a quant, and nothing to read the group through.
    if relation_exists('stock_quants'):
        op.execute(_BACKFILL)


def downgrade() -> None:
    op.drop_constraint('fk_wms_pick_lines_lot_id', 'wms_pick_lines', type_='foreignkey')
    op.drop_constraint(
        'fk_wms_pick_lines_anchor_id', 'wms_pick_lines', type_='foreignkey'
    )
    op.drop_column('wms_pick_lines', 'lot_id')
    op.drop_column('wms_pick_lines', 'anchor_id')
