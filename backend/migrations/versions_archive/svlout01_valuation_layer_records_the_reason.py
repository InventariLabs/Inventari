"""a valuation layer says why the stock left

Revision ID: svlout01
Revises: roleorg01
Create Date: 2026-08-28

``direction`` has been on this table since it was created and has only ever
held ``'IN'``. Stock leaving inventory drained the remaining quantity of the
receipt layers, recomputed the average, and left no record of what the
outflow was worth — so the one question the waste and consumption reports
exist to answer had no source, and they read it out of a JSON blob in the
item history where nothing writes it.

Every ERP posts the value of an outgoing move at the moment it happens, at
the cost in force then, and never recomputes it: a report about March has to
say the same thing in December. This column is what lets the outgoing layer
be attributed — a use is not a disposal, and the report is entirely about
telling those apart. ``direction`` alone cannot say it, and the destination
location (Odoo's way) is not known at the moment the quantity changes.

``item_id`` is the record the stock left, so the report can name a product
without splitting one template's value across the several records that share
it. ``document_line_id`` has always done the same job for the document paths;
this is its counterpart for the ones that start from a record on a shelf. It
goes NULL when the record is purged, exactly as the reports already lose a
purged item's name.

Nothing is written backwards. Layers that predate this are outgoing moves
that were never valued, and stamping them with today's average would put a
number into the ledger that was never true — and would make March's figure
move every time a later delivery shifted the average. A period before the
cut-over has an unknown value, not a zero.

The reports tell the two apart without a cut-over date: an outflow that has
no layer beside it is one this ledger never priced, and a window containing
one of those reports an unknown rather than a total. Nothing to configure,
nothing to keep in step with the migration.
"""

import sqlalchemy as sa
from alembic import op

revision = 'svlout01'
down_revision = 'roleorg01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'stock_valuation_layers',
        sa.Column('reason', sa.String(length=30), nullable=True),
    )
    op.add_column(
        'stock_valuation_layers',
        sa.Column(
            'item_id',
            sa.UUID(),
            sa.ForeignKey('items.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.create_index(
        'ix_svl_org_direction_reason',
        'stock_valuation_layers',
        ['organization_id', 'direction', 'reason'],
    )


def downgrade() -> None:
    op.drop_index('ix_svl_org_direction_reason', table_name='stock_valuation_layers')
    op.drop_column('stock_valuation_layers', 'item_id')
    op.drop_column('stock_valuation_layers', 'reason')
