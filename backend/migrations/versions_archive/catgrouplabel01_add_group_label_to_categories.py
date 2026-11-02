"""add group_label to categories

Revision ID: catgrouplabel01
Revises: catorg01
Create Date: 2026-08-21

``group_label`` (VARCHAR(50), nullable) is the organisation-chosen
grouping label for categories — what the categories filter groups by and what
the user types in the category form. A label, not a code: no enum, no
server default, no backfill (legacy ``category_type`` codes stay readable via
the ``group_label ?? category_type`` fallback in the filter).
"""

import sqlalchemy as sa
from alembic import op

revision = 'catgrouplabel01'
down_revision = 'catorg01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('categories', sa.Column('group_label', sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column('categories', 'group_label')
