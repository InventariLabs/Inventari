"""add the quarantine shelf to the document profile.

Revision ID: doc_quarantine_shelf01
Revises: doc_pick_line_lots01
Create Date: 2026-10-17

``document_profiles.quarantine_location_id`` names the shelf a receipt line
whose goods are held back is put on when it has no batch to hold back.

``doc_pick_line_lots01`` branched from ``doc_shipments01`` in parallel and
landed first; this revision is rebased onto it so ``alembic upgrade head``
keeps a single head.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_quarantine_shelf01'
down_revision: str | None = 'doc_pick_line_lots01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'document_profiles',
        sa.Column(
            'quarantine_location_id',
            sa.Uuid(),
            sa.ForeignKey('storage_locations.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('document_profiles', 'quarantine_location_id')
