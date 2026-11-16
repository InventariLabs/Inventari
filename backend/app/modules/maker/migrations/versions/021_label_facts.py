"""maker module — what a product's label says of it.

``maker_label_facts`` holds, per organization and product, the name the
product goes under in an ingredient list, the allergens it contains (NULL
until a person has checked them) and the ones it may contain. A made
product's ingredient list and allergens are computed from its recipe out of
these facts on its ingredients. Kept here rather than on
``product_templates`` for the reason the shelf lives are: a product can be a
catalogue row shared by every organization.

Revision ID: 021_label_facts
Revises: 020_staged_runs_and_stock_first
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '021_label_facts'
down_revision: str | None = '020_staged_runs_and_stock_first'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'maker_label_facts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('product_template_id', sa.Uuid(), nullable=False),
        sa.Column('label_name', sa.String(255), nullable=True),
        sa.Column('allergens', postgresql.JSONB(), nullable=True),
        sa.Column(
            'may_contain',
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['product_template_id'], ['product_templates.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'organization_id',
            'product_template_id',
            name='uq_maker_label_facts_org_template',
        ),
    )


def downgrade() -> None:
    op.drop_table('maker_label_facts')
