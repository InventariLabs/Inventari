"""add source_reorder_rule_id to purchase_order_lines

Revision ID: po_linesrc01
Revises: po_settings01
Create Date: 2026-09-14

A draft PO raised from replenishment alerts groups several reorder rules
under one supplier, so the provenance reference lives on the line, not
the header: each line remembers the rule whose alert created it. Nullable
— manually written orders have no source rule. SET NULL on rule delete:
the order line is a fact about a purchase and outlives the rule.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'po_linesrc01'
down_revision: str | None = 'po_settings01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'purchase_order_lines',
        sa.Column(
            'source_reorder_rule_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('po_reorder_rules.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.create_index(
        'ix_purchase_order_lines_source_reorder_rule_id',
        'purchase_order_lines',
        ['source_reorder_rule_id'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_purchase_order_lines_source_reorder_rule_id',
        table_name='purchase_order_lines',
    )
    op.drop_column('purchase_order_lines', 'source_reorder_rule_id')
