"""add target_location_id to document_lines.

Revision ID: doc_line_target01
Revises: doc_core_fks01
Create Date: 2026-09-15

A putaway rule speaks about goods, not about the shelf a person is
standing at. When that shelf is full, the worker needs to say so on the
line — before executing, not after hauling the goods somewhere the books
never heard of. This column carries the line's own destination; unset
lines keep following the rule and the document, exactly as before.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_line_target01'
down_revision: str | None = 'doc_core_fks01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'document_lines',
        sa.Column(
            'target_location_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('document_lines', 'target_location_id')
