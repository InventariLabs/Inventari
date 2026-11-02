"""maker module — remember whether an order was born over stock.

``maker_production_orders.short_at_create`` (BOOLEAN, NOT NULL, default false):
whether the planned consumption already exceeded stock when the order was
created (recomputed when a draft's planned_qty changes). The refusal dialog
used to invent history — "these ingredients ran out since the draft was
created" — for an order that was never satisfiable; with the flag recorded
at birth the sentence can tell that case from a real shortage.

Also sets the organization default shortage strategy to WARN: an order over
stock still gets created, but with a warning instead of silence. Rows that
already exist keep the value they were saved with.

Revision ID: 010_add_short_at_create
Revises: 009_add_order_number
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '010_add_short_at_create'
down_revision: str | None = '009_add_order_number'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'maker_production_orders',
        sa.Column(
            'short_at_create',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
    )
    op.alter_column(
        'maker_module_settings',
        'create_on_shortage_strategy',
        server_default='WARN',
    )


def downgrade() -> None:
    op.alter_column(
        'maker_module_settings',
        'create_on_shortage_strategy',
        server_default='ALLOW',
    )
    op.drop_column('maker_production_orders', 'short_at_create')
