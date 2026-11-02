"""move production_date off Item to meta_data['manufacturing']

Item.production_date was a food/manufacturing residual with no readers or
writers in application code (zero references in services/items, schemas, seeds,
or conftest). The authoritative production_date for lot-tracked items lives on
StockLot. Any pre-existing data is preserved in meta_data before the column is
dropped.

Revision ID: moveproddate01
Revises: movefreezedate01
Create Date: 2026-06-21 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'moveproddate01'
down_revision: Union[str, None] = 'movefreezedate01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE items
            SET meta_data = jsonb_set(
                CASE
                    WHEN meta_data IS NULL OR jsonb_typeof(meta_data) <> 'object'
                        THEN '{}'::jsonb
                    ELSE meta_data
                END,
                '{manufacturing,production_date}',
                to_jsonb(production_date::text),
                true
            )
            WHERE production_date IS NOT NULL
            """
        )
    )
    op.drop_column('items', 'production_date')


def downgrade() -> None:
    op.add_column('items', sa.Column('production_date', sa.Date(), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE items
            SET production_date = (meta_data->'manufacturing'->>'production_date')::date
            WHERE jsonb_typeof(meta_data) = 'object'
              AND meta_data->'manufacturing'->>'production_date' IS NOT NULL
              AND (meta_data->'manufacturing'->>'production_date') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE items
            SET meta_data = meta_data #- '{manufacturing,production_date}'
            WHERE jsonb_typeof(meta_data) = 'object'
              AND meta_data ? 'manufacturing'
            """
        )
    )
