"""add emoji and color to categories

This migration adds two nullable presentation-only
columns to ``categories``:

- ``emoji``: user-overridable single-glyph (e.g. ``"🥚"``). NULL = "let the
  frontend cascade resolve via keyword guess / vertical default".
- ``color``: a Tailwind palette KEY (e.g. ``"indigo"``), NOT a hex value,
  because Tailwind's JIT purge strips dynamic ``bg-[#...]`` classes.

Both columns are nullable so:
1. The migration is zero-downtime (no data backfill needed — the cascade
   fills them lazily on render).
2. Existing rows get NULL and the cascade handles them on day 1.

Downgrade drops both columns. The existing ``icon`` (Lucide) column is
preserved for backward compatibility — it will be removed in a follow-up
cleanup migration once the emoji migration is confirmed stable.

Revision ID: cv2_emoji_color_001
Revises: neutralstorage01
Create Date: 2026-07-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'cv2_emoji_color_001'
down_revision: str | None = 'neutralstorage01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'categories',
        sa.Column('emoji', sa.String(length=32), nullable=True),
    )
    op.add_column(
        'categories',
        sa.Column('color', sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('categories', 'color')
    op.drop_column('categories', 'emoji')
