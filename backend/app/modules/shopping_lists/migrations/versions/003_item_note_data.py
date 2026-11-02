"""shopping_lists: add note_data to shopping_list_items.

Structured note parts for service-composed lines (meal-plan shopping): the
interface re-renders them in the reader's language instead of the language
the generation ran in. The plain `notes` column stays as the composed
fallback for consumers that cannot re-render.

Revision ID: 003_item_note_data
Revises: 002_item_template
Create Date: 2026-08-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '003_item_note_data'
down_revision: str | None = '002_item_template'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'shopping_list_items',
        sa.Column('note_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('shopping_list_items', 'note_data')
