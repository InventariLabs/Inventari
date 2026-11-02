"""Drop product_templates.current_valuation_rate — one number, many organizations

Valuation layers belong to an organization. The AVCO rate computed from them
was cached in a column on ``product_templates``, and a global template — the
whole default catalogue — is a single row every organization shares. So the
cached figure belonged to whichever organization had last taken a delivery:
an organization could read another's purchase cost off a catalogue product,
and value its own stock with it. Which one won depended on write order.

The rate is computed per organization from that organization's own layers now,
so there is nothing left to cache and nothing to keep in step. Reads go through
``core_api.valuation.get_current_rate_async`` or its batch counterpart; the one
endpoint that returned the figure to a screen fills it the same way.

Nothing is backfilled on downgrade. The column comes back empty, which is the
only value that was ever true for more than one organization at a time.

Revision ID: avcoshared01
Revises: auditimm01
"""

import sqlalchemy as sa
from alembic import op

revision = 'avcoshared01'
down_revision = 'auditimm01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column('product_templates', 'current_valuation_rate')


def downgrade() -> None:
    op.add_column(
        'product_templates',
        sa.Column(
            'current_valuation_rate',
            sa.Numeric(precision=12, scale=2),
            nullable=True,
        ),
    )
