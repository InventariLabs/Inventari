"""add removal_strategy to product_templates

Revision ID: s6_6_strategy01
Revises: stockmove02
Create Date: 2026-06-23

ProductTemplate gains a nullable ``removal_strategy`` column ('FIFO' or
'FEFO').  Nullable so existing rows preserve their StockQuant-level
default behaviour; new writes and the resolver fill in the default.

The resolver (app.services.stock_service.resolve_removal_strategy)
uses template.removal_strategy, falling back to 'FIFO' when unset.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 's6_6_strategy01'
down_revision: str | None = 'stockmove02'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'product_templates',
        sa.Column('removal_strategy', sa.String(10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('product_templates', 'removal_strategy')
