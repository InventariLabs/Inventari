"""mark a document line whose expected quantity is a typed count.

Revision ID: doc_count_expectation01
Revises: doc_pick_order_strategy01
Create Date: 2026-10-25

``document_lines.expected_is_count`` says the line's expected quantity is
the count somebody typed to get a row on the receive sheet, not a figure
from an order or a delivery note. Receiving such a line has no expectation
to exceed, so a count above it is not a surplus past the tolerance. Every
existing line keeps the old meaning: its expectation is a real one.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_count_expectation01'
down_revision: str | None = 'doc_pick_order_strategy01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'document_lines',
        sa.Column(
            'expected_is_count',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
    )


def downgrade() -> None:
    op.drop_column('document_lines', 'expected_is_count')
