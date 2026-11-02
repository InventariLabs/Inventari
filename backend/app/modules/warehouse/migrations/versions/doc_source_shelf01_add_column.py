"""add the source shelf to document lines.

Revision ID: doc_source_shelf01
Revises: doc_held_quantity01
Create Date: 2026-10-18

A dispatch, transfer or internal issue may name a zone as its source. Each
of its lines then takes from one shelf below the zone, and the line records
which one at confirmation, so the hold, the picking and the draw read the
same shelf. Unset lines keep following the document's source and the
record's shelf, exactly as before.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_source_shelf01'
down_revision: str | None = 'doc_held_quantity01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'document_lines',
        sa.Column(
            'source_location_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('document_lines', 'source_location_id')
