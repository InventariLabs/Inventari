"""a picking session carries its own multiplier: picking_sessions.scale

Revision ID: 007_picking_session_scale
Revises: 006_backfill_picking_trace
Create Date: 2026-09-30

A session started from a scale factor (``scale=1.4``) had nowhere to put
the fraction: ``servings`` is a whole count, so the factor could only
reach the session folded into it — rounded — and the session disagreed
with itself on the next read, which re-derives the sheet from the row.

``scale`` is the multiplier in its own column, ``Numeric(10, 3)`` like
every quantity in this module so a ``Decimal`` travels the whole chain
without a binary float in between. ``servings`` stays untouched: NULL in
``scale`` means the session is portioned by servings, exactly what every
session before this column is, so there is nothing to backfill.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '007_picking_session_scale'
down_revision: str | None = '006_backfill_picking_trace'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'picking_sessions',
        sa.Column('scale', sa.Numeric(10, 3), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('picking_sessions', 'scale')
