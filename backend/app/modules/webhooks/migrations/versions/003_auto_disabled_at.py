"""add auto_disabled_at to webhook_endpoints (why an endpoint is off).

``is_active = false`` had two causes and one appearance: an administrator
pausing an endpoint and the circuit breaker switching it off after repeated
failures. The card named the second one for both. This column records the
moment the breaker acted, so the cause is read rather than guessed.

Left NULL for existing rows on purpose: nothing in the schema says which of
the two happened to them, and a backfill would be a guess written down as a
fact.

Revision ID: 003_auto_disabled_at
Revises: 002_claimed_at
Create Date: 2026-08-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '003_auto_disabled_at'
down_revision: str | None = '002_claimed_at'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'webhook_endpoints',
        sa.Column('auto_disabled_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('webhook_endpoints', 'auto_disabled_at')
