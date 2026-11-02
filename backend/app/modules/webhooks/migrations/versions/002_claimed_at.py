"""add claimed_at to webhook_delivery_logs (claim-then-deliver).

The retry worker no longer holds ``FOR UPDATE`` row locks across HTTP calls.
It claims a batch in a short transaction (status ``retrying`` +
``claimed_at``), delivers outside the lock, and commits per row. Stale
claims are reclaimed by later runs.

Revision ID: 002_claimed_at
Revises: 001_initial
Create Date: 2026-07-29

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '002_claimed_at'
down_revision: str | None = '001_initial'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'webhook_delivery_logs',
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('webhook_delivery_logs', 'claimed_at')
