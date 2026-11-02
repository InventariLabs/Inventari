"""Add storage_location_id to stock_take_items.

Revision ID: 008_a_row_names_its_shelf
Revises: 007_timestamps_carry_their_zone
Create Date: 2026-10-18

A count covers a location and every descendant, and a warehouse counts it
shelf by shelf. A row said where it was counted only in free text — the
record's shelf code or the location path — so nothing recorded on which
shelf a counted quantity actually stood, and goods found on another shelf
had nowhere to be written down. The row now names its shelf.

The column is nullable: a shelf that is deleted leaves the row and its
counting evidence behind. Existing rows are filled in by the next revision.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '008_a_row_names_its_shelf'
down_revision: str | None = '007_timestamps_carry_their_zone'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'stock_take_items',
        sa.Column('storage_location_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_stock_take_items_storage_location_id',
        'stock_take_items',
        'storage_locations',
        ['storage_location_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_stock_take_items_storage_location_id',
        'stock_take_items',
        type_='foreignkey',
    )
    op.drop_column('stock_take_items', 'storage_location_id')
