"""add the held quantity to document lines.

Revision ID: doc_held_quantity01
Revises: doc_quarantine_shelf01
Create Date: 2026-10-17

``document_lines.held_quantity`` says how much of what a receipt line
received is held back — damaged goods or goods waiting for a quality
decision. The quantity is booked, but outside available stock, and it does
not count as received on the order line the receipt fulfils.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_held_quantity01'
down_revision: str | None = 'doc_quarantine_shelf01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'document_lines',
        sa.Column(
            'held_quantity',
            sa.Numeric(12, 3),
            nullable=False,
            server_default=sa.text('0'),
        ),
    )


def downgrade() -> None:
    op.drop_column('document_lines', 'held_quantity')
