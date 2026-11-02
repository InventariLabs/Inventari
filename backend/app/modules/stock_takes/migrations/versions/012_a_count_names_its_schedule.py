"""Add stock_takes.schedule_id: the schedule that generated a count.

Revision ID: 012_a_count_names_its_schedule
Revises: 011_a_shelf_can_be_closed
Create Date: 2026-10-20

To do lists a due count as work, and has to tell one that has not begun from
one under way or finished today. A generated count is a stock take like any
other, so the schedule it came from is kept on it. Counts made before this
column stay unlinked.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '012_a_count_names_its_schedule'
down_revision: str | None = '011_a_shelf_can_be_closed'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'stock_takes',
        sa.Column(
            'schedule_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('cycle_count_schedules.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.create_index('ix_stock_takes_schedule_id', 'stock_takes', ['schedule_id'])


def downgrade() -> None:
    op.drop_index('ix_stock_takes_schedule_id', table_name='stock_takes')
    op.drop_column('stock_takes', 'schedule_id')
