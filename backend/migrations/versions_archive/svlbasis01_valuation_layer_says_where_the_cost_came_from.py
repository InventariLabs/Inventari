"""a valuation layer says where its cost came from

Revision ID: svlbasis01
Revises: avcoshared01
Create Date: 2026-08-29

Stock arriving without a price got two different answers depending on which
door it came through. A surplus off a count, a quantity raised by hand and a
correction with no price were all posted at 0.00; a receipt document whose
line carried no price posted no layer at all. The first dilutes the average
and understates the assets on every single surplus — the accounting act and
ERP practice both say a surplus is valued at cost of acquisition or at the
running average, never at nothing. The second breaks the equality between
what stands on the shelf and what the layers add up to, and no report looks
for that gap: reconciliation compares records against quants and has never
looked at the cost history at all.

Both doors now lead to one policy: value it at the organization's own current
rate, and when there is no rate to use, post the layer and mark it. This
column is that mark. It also keeps the outgoing half honest — an outflow the
layers could not cover is now posted as unknown rather than skipped, and the
"is this window valued" question knows to exclude it instead of counting an
unpriced move as priced.

Existing rows are marked ``stated``, because that is what the code claimed
when it wrote them. Nothing distinguishes a receipt genuinely priced at zero
from one where nobody named a price, and that is precisely what could not be
told apart before this column — the history keeps its ambiguity rather than
having a guess written over it.
"""

import sqlalchemy as sa
from alembic import op

revision = 'svlbasis01'
down_revision = 'avcoshared01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'stock_valuation_layers',
        sa.Column(
            'cost_basis',
            sa.String(length=10),
            nullable=False,
            server_default='stated',
        ),
    )
    # The server default exists only to fill the existing rows. Leaving it in
    # place would let a future insert that forgets the column look deliberate.
    op.alter_column('stock_valuation_layers', 'cost_basis', server_default=None)


def downgrade() -> None:
    op.drop_column('stock_valuation_layers', 'cost_basis')
