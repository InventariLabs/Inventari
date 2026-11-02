"""add corrects_line_id to document_lines.

Revision ID: doc_corrects_line01
Revises: doc_extra_costs01
Create Date: 2026-09-01

A correction and a return both restate one line of one earlier document, and
neither wrote down which. The link was carried only in the request that
created them, so nothing afterwards could ask the two questions that matter:
how much of that line has already been taken back, and which receipt layer
the goods being taken back arrived on.

Without the first, every correction was checked against the original line on
its own, so two corrections of minus ten against a line that received ten
both passed. Without the second, taking goods back off the shelf drained
whatever was oldest instead of the delivery being corrected, and the value
that left the books was some other delivery's price.

Existing rows keep NULL — the link was never recorded, and guessing it from
quantities would invent history.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_corrects_line01'
down_revision: str | None = 'doc_extra_costs01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'document_lines',
        sa.Column(
            'corrects_line_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('document_lines.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.create_index(
        'ix_document_lines_corrects_line_id',
        'document_lines',
        ['corrects_line_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_document_lines_corrects_line_id', table_name='document_lines')
    op.drop_column('document_lines', 'corrects_line_id')
