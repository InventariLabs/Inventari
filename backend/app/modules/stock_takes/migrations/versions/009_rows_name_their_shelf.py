"""Fill stock_take_items.storage_location_id for the rows that predate it.

Revision ID: 009_rows_name_their_shelf
Revises: 008_a_row_names_its_shelf
Create Date: 2026-10-18

Every row counted a record, and until a row could name a shelf of its own
the shelf it counted was the one its record stands on. That is the best
answer there is for the rows already written: a record moved since then
names its new shelf, and a row whose record is gone keeps NULL.

Downgrade empties the column again.
"""

from collections.abc import Sequence

from alembic import op

revision: str = '009_rows_name_their_shelf'
down_revision: str | None = '008_a_row_names_its_shelf'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE stock_take_items AS row
        SET storage_location_id = items.storage_location_id
        FROM items
        WHERE items.id = row.item_id
          AND row.storage_location_id IS NULL
        """
    )


def downgrade() -> None:
    op.execute('UPDATE stock_take_items SET storage_location_id = NULL')
