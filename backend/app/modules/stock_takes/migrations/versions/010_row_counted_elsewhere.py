"""Add expected_location_id to stock_take_items.

Revision ID: 010_row_counted_elsewhere
Revises: 009_rows_name_their_shelf
Create Date: 2026-10-18

A unit with a serial number, or goods with no product card, found on another
location of the count cannot become a second record there: the serial number
is unique, and the catalogue has no card to open one from. Its one row moves
to the location it was found on instead, and this column keeps the location
its record stands on, so closing the count can move the record and the report
can show the shortage there beside the surplus where it was found.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '010_row_counted_elsewhere'
down_revision: str | None = '009_rows_name_their_shelf'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'stock_take_items',
        sa.Column('expected_location_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_stock_take_items_expected_location_id',
        'stock_take_items',
        'storage_locations',
        ['expected_location_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_stock_take_items_expected_location_id',
        'stock_take_items',
        type_='foreignkey',
    )
    op.drop_column('stock_take_items', 'expected_location_id')
