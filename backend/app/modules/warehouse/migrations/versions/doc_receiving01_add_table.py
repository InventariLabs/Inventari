"""create document_warehouse_receiving table, link a putaway to its receipt line.

Revision ID: doc_receiving01
Revises: doc_complete_on_approval01
Create Date: 2026-10-21

A warehouse that receives at the dock and shelves later had no way to say
so: every receipt put its goods straight on the shelf the putaway rules
chose. One row per warehouse now records the choice — one step or two —
and the receiving area two-step receipts land in. No row is the default,
one step, so existing organizations receive exactly as before.

``document_lines.puts_away_line_id`` names, on the line of a putaway move,
the receipt line whose goods it carried out of the receiving area. Each
receipt line is a task of its own, and the link is how a task knows how
much of its line is still waiting.

Downgrade drops the column and the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_receiving01'
down_revision: str | None = 'doc_complete_on_approval01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'document_warehouse_receiving',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column(
            'organization_id',
            sa.UUID(),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'warehouse_id',
            sa.UUID(),
            sa.ForeignKey('storage_locations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'two_step', sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            'receiving_location_id',
            sa.UUID(),
            sa.ForeignKey('storage_locations.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            'organization_id',
            'warehouse_id',
            name='uq_document_warehouse_receiving_org_warehouse',
        ),
    )
    op.create_index(
        'ix_document_warehouse_receiving_organization_id',
        'document_warehouse_receiving',
        ['organization_id'],
    )
    op.add_column(
        'document_lines',
        sa.Column(
            'puts_away_line_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('document_lines.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.create_index(
        'ix_document_lines_puts_away_line_id',
        'document_lines',
        ['puts_away_line_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_document_lines_puts_away_line_id', table_name='document_lines')
    op.drop_column('document_lines', 'puts_away_line_id')
    op.drop_index(
        'ix_document_warehouse_receiving_organization_id',
        'document_warehouse_receiving',
    )
    op.drop_table('document_warehouse_receiving')
