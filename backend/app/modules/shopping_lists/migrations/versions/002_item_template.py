"""shopping_lists: add template_id to shopping_list_items.

Links a shopping-list line to a ProductTemplate so un-purchased lines can be
grouped into a Purchase Order (Shopping List → PO conversion).

Revision ID: 002_item_template
Revises: 001_initial
Create Date: 2026-08-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '002_item_template'
down_revision: str | None = '001_initial'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'shopping_list_items',
        sa.Column(
            'template_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('product_templates.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('shopping_list_items', 'template_id')
