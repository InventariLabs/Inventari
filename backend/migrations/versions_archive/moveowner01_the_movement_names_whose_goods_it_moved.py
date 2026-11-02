"""the movement names whose goods it moved: stock_moves.owner_id

Revision ID: moveowner01
Revises: holdguard01
Create Date: 2026-09-29

A movement row named the batch it moved but not whose goods they were,
while everything beside it — the quant it changed, the reservation row
that held it — carries the owner. The one rule for every door (recorded
in ``docs/subsystems/STOCK.md``): the owner
comes from the document line, so the movement says whose goods left or
arrived the same way the state says whose goods stand.

No backfill: the quants carry no history, and today's movements are all
of the organization's own goods — no door creates a consignor's stock
yet, so there is nothing a backfill could say. Rows before this change
read as the organization's own, which is what they are.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'moveowner01'
down_revision: str | None = 'quantdrop01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'stock_moves',
        sa.Column(
            'owner_id',
            sa.Uuid(),
            sa.ForeignKey('partners.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.create_index('ix_stock_moves_owner_id', 'stock_moves', ['owner_id'])


def downgrade() -> None:
    op.drop_index('ix_stock_moves_owner_id', table_name='stock_moves')
    op.drop_column('stock_moves', 'owner_id')
