"""Keep every counting pass, and let a row be sent back to be counted again.

Revision ID: 004_stock_take_counts
Revises: 003_discrepancy_reason_code
Create Date: 2026-08-31

A recount used to overwrite the first number, which threw away the one
thing that makes a correction believable: two people walking the same shelf
and arriving at the same figure. A disagreement between them is information
too. So each pass is a row, the way SAP keeps the original document beside
its recount and Dynamics hangs many recordings off one inventory order.

``recount_requested`` marks a row sent back; finalize refuses to post it
until somebody has counted it again.

Existing counted rows get no pass rows: nobody recorded who counted them or
when, and inventing a first pass would put a name on work the records never
attributed. Their ``counted_quantity`` still says what was counted.

Downgrade drops the table and the flag.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '004_stock_take_counts'
down_revision: str | None = '003_discrepancy_reason_code'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'stock_take_items',
        sa.Column(
            'recount_requested',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        'stock_take_counts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'stock_take_item_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('stock_take_items.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Numeric(10, 3), nullable=False),
        sa.Column(
            'counted_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'counted_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        'ix_stock_take_counts_stock_take_item_id',
        'stock_take_counts',
        ['stock_take_item_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_stock_take_counts_stock_take_item_id', table_name='stock_take_counts')
    op.drop_table('stock_take_counts')
    op.drop_column('stock_take_items', 'recount_requested')
