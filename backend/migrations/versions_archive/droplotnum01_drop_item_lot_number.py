"""drop dead item.lot_number column

Removes the misleading, non-authoritative ``lot_number`` scalar from the
Core ``Item`` model. Lot tracking lives on the authoritative
``StockQuant.lot_id`` -> ``StockLot`` layer (populated by document receipts,
consumed via the cross-lot FIFO/FEFO strategy). A single ``Item`` row can
span multiple lots (1:N), so a scalar ``lot_number`` could not represent the
truth and only gave a false sense of traceability.

Revision ID: droplotnum01
Revises: pickitems01
Create Date: 2026-06-18 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'droplotnum01'
down_revision: Union[str, None] = 'pickitems01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_items_lot_number', table_name='items')
    op.drop_column('items', 'lot_number')


def downgrade() -> None:
    op.add_column(
        'items',
        sa.Column('lot_number', sa.String(length=100), nullable=True),
    )
    op.create_index('ix_items_lot_number', 'items', ['lot_number'], unique=False)
