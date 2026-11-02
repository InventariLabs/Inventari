"""a storage location carries a plain ordering number.

Revision ID: locseq01
Revises: partnerconsumer01
Create Date: 2026-10-16

Shelf codes rarely say in which order a place is walked, so anything that
visits locations one after another sorted them by code. ``sequence`` is a
nullable number a person sets on the location; walks follow it, lowest
first, and a location without one comes after the numbered ones. Existing
rows get none, which keeps the order by code they had.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'locseq01'
down_revision: str | None = 'partnerconsumer01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'storage_locations', sa.Column('sequence', sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('storage_locations', 'sequence')
