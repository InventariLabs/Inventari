"""a valuation layer says which currency its cost is in

Revision ID: svlcurrency01
Revises: modcat01
Create Date: 2026-08-26

``unit_cost`` had no currency beside it and every reader took it for the
organization's own. A receipt of 100 × 40.10 PLN in an organization keeping
its books in USD wrote 40.10 into the cost history, and nothing downstream
could tell that those were złoty. The document register already knows —
receipts carry the order's currency — the valuation layer was the one place
with no way even to ask the question.

The backfill is the organization's currency, which is what every reader
already assumed. It changes nothing about the past; it only writes down what
was being taken for granted, so that from here on a layer in another currency
can be seen for what it is.

Layers whose organization has no currency of its own stay NULL, and the
readers treat NULL as the organization's currency — the same assumption,
still explicit.
"""

import sqlalchemy as sa
from alembic import op

revision = 'svlcurrency01'
down_revision = 'modcat01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'stock_valuation_layers',
        sa.Column('currency', sa.String(length=3), nullable=True),
    )
    op.execute(
        """
        UPDATE stock_valuation_layers AS svl
        SET currency = o.currency
        FROM organizations AS o
        WHERE o.id = svl.organization_id
          AND o.currency IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column('stock_valuation_layers', 'currency')
