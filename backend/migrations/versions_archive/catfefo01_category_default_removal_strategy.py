"""add default_removal_strategy to categories

Revision ID: catfefo01
Revises: locseq01
Create Date: 2026-10-16

A category can name the removal strategy ('FIFO' or 'FEFO') the products
created under it start with. Nullable and without a default: existing
categories name none, and a product minted under them keeps starting FIFO.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'catfefo01'
down_revision: str | None = 'locseq01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'categories',
        sa.Column('default_removal_strategy', sa.String(length=10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('categories', 'default_removal_strategy')
