"""create wms_pick_line_lots table (what a pick line took from each batch).

Revision ID: doc_pick_line_lots01
Revises: doc_shipments01
Create Date: 2026-10-17

A pick line holds one planned batch, but a quantity can be picked from
several (25 where the first batch holds 20). This table keeps what each
batch gave, so closing the session can write the document one line per batch
and the books name the batches that left the shelf. Existing lines get no
rows: a line with none is served by the product's strategy at completion, as
every line was before.

Downgrade drops the table; lines then complete by the strategy again.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_pick_line_lots01'
down_revision: str | None = 'doc_shipments01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'wms_pick_line_lots',
        sa.Column(
            'pick_line_id',
            sa.UUID(),
            sa.ForeignKey('wms_pick_lines.id', ondelete='CASCADE'),
            primary_key=True,
        ),
        sa.Column(
            'lot_id',
            sa.UUID(),
            sa.ForeignKey('stock_lots.id', ondelete='CASCADE'),
            primary_key=True,
        ),
        sa.Column('lot_name', sa.String(length=100), nullable=False),
        sa.Column('quantity', sa.Numeric(12, 3), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
    )
    op.create_index('ix_wms_pick_line_lots_lot_id', 'wms_pick_line_lots', ['lot_id'])


def downgrade() -> None:
    op.drop_index('ix_wms_pick_line_lots_lot_id', table_name='wms_pick_line_lots')
    op.drop_table('wms_pick_line_lots')
