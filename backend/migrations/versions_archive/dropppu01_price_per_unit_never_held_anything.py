"""Drop items.price_per_unit — a twin of purchase_price that was never written

An item carried two cost columns with one meaning and the opposite names.
``purchase_price`` is the per-unit rate: it opens a valuation layer at that unit
cost, AVCO is computed from those layers, and a production cost is rate ×
quantity. ``price_per_unit`` — commented "price per kg/L" — was written by
nothing and read by nothing; ``GET /items`` returned null for it on every row
since the initial schema.

Keeping it was not free. It is the reason the form's own label could look
right while meaning the other thing: the field named "per unit" was not the
field that behaves per unit. Dropped, so there is one column and one name.

Data loss on downgrade is nil in any sense that matters — the column comes back
empty, which is the only state it has ever been in.

Revision ID: dropppu01
Revises: svlout01
"""

import sqlalchemy as sa
from alembic import op

revision = 'dropppu01'
down_revision = 'svlout01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column('items', 'price_per_unit')


def downgrade() -> None:
    op.add_column(
        'items',
        sa.Column('price_per_unit', sa.Numeric(precision=10, scale=2), nullable=True),
    )
