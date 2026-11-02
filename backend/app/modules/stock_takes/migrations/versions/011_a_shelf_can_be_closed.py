"""Add stock_take_closed_locations: the shelves a counter closed.

Revision ID: 011_a_shelf_can_be_closed
Revises: 010_row_counted_elsewhere
Create Date: 2026-10-19

A counter closes each shelf when done with it. What it was expected to hold
and nobody counted is counted as none, and a shelf found empty is confirmed
as empty. Either way the shelf, who closed it and when are kept here, so the
report can say which shelves were looked at — an empty one leaves no row of
its own to say so.

Downgrade drops the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '011_a_shelf_can_be_closed'
down_revision: str | None = '010_row_counted_elsewhere'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'stock_take_closed_locations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'stock_take_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('stock_takes.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'storage_location_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('path', sa.Text(), nullable=False),
        sa.Column('empty', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            'closed_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'closed_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            'stock_take_id',
            'storage_location_id',
            name='uq_stock_take_closed_locations_location',
        ),
    )
    op.create_index(
        'ix_stock_take_closed_locations_stock_take_id',
        'stock_take_closed_locations',
        ['stock_take_id'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_stock_take_closed_locations_stock_take_id',
        table_name='stock_take_closed_locations',
    )
    op.drop_table('stock_take_closed_locations')
