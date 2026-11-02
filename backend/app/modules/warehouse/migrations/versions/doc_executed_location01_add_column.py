"""add executed_location_id to document_lines.

Revision ID: doc_executed_location01
Revises: doc_reason_code01
Create Date: 2026-08-28

A receipt does not always land where the document asked. A putaway rule can
send the goods to another shelf, and until now nothing on the document said
so: the header named one place, the record another and the ledger a third.

This column records where the line's goods actually went, so the document
can show it next to the place it asked for.

Existing rows keep NULL — nobody wrote down where those went.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_executed_location01'
down_revision: str | None = 'doc_reason_code01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'document_lines',
        sa.Column(
            'executed_location_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('document_lines', 'executed_location_id')
