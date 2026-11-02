"""maker module — add cancel_reason and produced_item_id to production orders.

Adds two nullable columns to ``maker_production_orders``:
- ``cancel_reason`` (VARCHAR 500) — optional reason captured at cancel time,
  stored inline for quick display (mirrors stock_takes.discrepancy_reason).
- ``produced_item_id`` (UUID → items.id) — link to the output Item created
  during completion, so the detail page can deep-link to the produced batch.

Both columns are nullable so existing rows remain valid without backfill.

Revision ID: 002_cancel_reason_produced_item
Revises: 001_initial
Create Date: 2026-07-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '002_cancel_reason_produced_item'
down_revision: str | None = '001_initial'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'maker_production_orders',
        sa.Column('cancel_reason', sa.String(500), nullable=True),
    )
    op.add_column(
        'maker_production_orders',
        sa.Column(
            'produced_item_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('items.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('maker_production_orders', 'produced_item_id')
    op.drop_column('maker_production_orders', 'cancel_reason')
