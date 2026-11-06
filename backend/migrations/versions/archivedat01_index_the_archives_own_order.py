"""index the archive's own order - what the archived list pages by

The archived products list paged with ``OFFSET`` and a count on every
request, sorted by the archive date alone. Nothing deletes an archived
record, so the archive only grows, and a page deep in it made the database
produce every row above it. It now pages by the last row the reader saw, and
that needs an index that is the order: newest archive date first (the day a
record was made where it carries none), the id breaking ties.

Live records are in it as well. The planner reads how many records share one
date from the statistics of this index, and PostgreSQL does not read them
from a partial one: with only the archived records in it, a page that started
inside a large group archived at one instant was estimated at a hundred rows
and sorted the whole group.

Revision ID: archivedat01
Revises: locnames02
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'archivedat01'
down_revision: str | None = 'locnames02'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        'ix_items_org_archived_at',
        'items',
        [
            'organization_id',
            'is_deleted',
            sa.text('coalesce(deleted_at, created_at) DESC'),
            'id',
        ],
    )


def downgrade() -> None:
    op.drop_index('ix_items_org_archived_at', table_name='items')
