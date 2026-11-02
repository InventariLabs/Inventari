"""maker module — human-facing production order numbers.

``maker_production_orders.number`` (VARCHAR(32), NULL for legacy rows) plus a
per-organization partial unique index. New orders get "PR/{YEAR}/{SEQ:04d}"
at creation; existing rows keep NULL and the interface falls back to the old
short-UUID display for them. Backfill by created_at would rewrite history
(ordering by id is not ordering by creation across hosts) — a number the row
never had is left as NULL instead of invented.

Revision ID: 009_add_order_number
Revises: 008_add_result_snapshot
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '009_add_order_number'
down_revision: str | None = '008_add_result_snapshot'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'maker_production_orders',
        sa.Column('number', sa.String(length=32), nullable=True),
    )
    op.create_index(
        'uq_prod_org_number',
        'maker_production_orders',
        ['organization_id', 'number'],
        unique=True,
        postgresql_where=sa.text('number IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_prod_org_number', table_name='maker_production_orders'
    )
    op.drop_column('maker_production_orders', 'number')
