"""mark the receipt layers that came from the organization's own books

A production run posts its product as a receipt layer worth the ingredients it
used, and undoing it posts the ingredients back the same way. The reports of
what was spent summed every receipt, so the same purchase was counted when the
ingredients were bought and again when they came out as a product.

``internal`` says which layers are those: True for goods that came out of the
organization's own books, False for everything bought. Layers already there
stay False — nothing on a layer recorded where it came from.

Revision ID: layerinternal01
Revises: layerreval01
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'layerinternal01'
down_revision: str | None = 'layerreval01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'stock_valuation_layers',
        sa.Column(
            'internal', sa.Boolean(), nullable=False, server_default=sa.text('false')
        ),
    )


def downgrade() -> None:
    op.drop_column('stock_valuation_layers', 'internal')
