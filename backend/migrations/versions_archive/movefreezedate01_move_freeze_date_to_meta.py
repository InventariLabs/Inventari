"""move item.freeze_date to meta_data['food']['freeze_date']

Removes the food-specific ``freeze_date`` column from the Core ``Item`` model
(it fails the 3-Vertical Test — freezing is a food-vertical concept). Existing
values are preserved under the ``meta_data.food.freeze_date`` namespace, and the
public API still exposes ``freeze_date`` via a meta_data-backed shim
(``services/items/_date_meta.py``), so this migration is transparent to API
consumers and the frontend.

Revision ID: movefreezedate01
Revises: e4f5a6b7c8d9
Create Date: 2026-06-21 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'movefreezedate01'
down_revision: Union[str, None] = 'e4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Backfill existing freeze_date values into meta_data['food']['freeze_date']
    # before dropping the column.
    #
    # Robustness: meta_data is JSONB and some legacy rows may contain a
    # non-object value (string/number/array/boolean) instead of an object, e.g.
    # from manual DB edits. ``jsonb_set`` fails on scalars with
    # ``cannot set path in scalar``. We coalesce any non-object value
    # (including NULL) into a fresh object first.
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
                '{food,freeze_date}',
                to_jsonb(freeze_date::text),
                true
            )
            WHERE freeze_date IS NOT NULL
            """
        )
    )
    op.drop_column('items', 'freeze_date')


def downgrade() -> None:
    op.add_column(
        'items',
        sa.Column('freeze_date', sa.Date(), nullable=True),
    )
    # Restore freeze_date from the namespaced meta_data slot. Guard against
    # rows whose meta_data is no longer an object.
    op.execute(
        sa.text(
            """
            UPDATE items
            SET freeze_date = (meta_data->'food'->>'freeze_date')::date
            WHERE jsonb_typeof(meta_data) = 'object'
              AND meta_data->'food'->>'freeze_date' IS NOT NULL
              AND (meta_data->'food'->>'freeze_date') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            """
        )
    )
    # Remove the migrated slot so the data shape matches pre-upgrade.
    op.execute(
        sa.text(
            """
            UPDATE items
            SET meta_data = meta_data - 'food'
            WHERE jsonb_typeof(meta_data) = 'object'
              AND meta_data ? 'food'
              AND (meta_data->'food') - 'freeze_date' = '{}'::jsonb
            """
        )
    )
