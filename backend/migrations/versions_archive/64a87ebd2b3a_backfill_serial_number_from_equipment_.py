"""backfill_serial_number_from_equipment_jsonb

Revision ID: 64a87ebd2b3a
Revises: 9f479e121c3a
Create Date: 2026-04-11 22:28:42.454584

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '64a87ebd2b3a'
down_revision: Union[str, None] = '9f479e121c3a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Backfill Item.serial_number from meta_data['equipment']['serial_number']
    # Only fills rows where serial_number is currently NULL to avoid overwriting.
    op.execute("""
        UPDATE items
        SET serial_number = meta_data->'equipment'->>'serial_number'
        WHERE
            meta_data->'equipment'->>'serial_number' IS NOT NULL
            AND meta_data->'equipment'->>'serial_number' <> ''
            AND serial_number IS NULL
    """)


def downgrade() -> None:
    # Data migration — downgrade is a no-op (safe to leave Core column populated).
    pass
