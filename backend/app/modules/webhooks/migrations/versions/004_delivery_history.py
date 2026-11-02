"""delivery history: delivery_id, abandon_reason, last_attempt_at.

Three columns, one reader: the operator comparing this module's history with
what their receiver actually received.

``delivery_id`` — the identity the receiver saw. It used to be rolled fresh
inside every attempt, so a retry arrived as a new event and nothing tied the
attempts together; now it is minted once with the row and sent in the header
and the payload body on every attempt. NULL only on rows written before this
change — an old row never had the id, and inventing one afterwards would be
a fact nobody's receiver ever saw.

``abandon_reason`` — why the application itself stopped trying (breaker cut,
endpoint switched off, endpoint deleted, module off). Abandonment used to
reuse the previous attempt's status code, so the history read our refusal as
the receiver's answer.

``last_attempt_at`` — when the attempt that produced the row's current
status ended. ``created_at`` is the enqueue time and drifts from the outcome
by the whole backoff.

Revision ID: 004_delivery_history
Revises: 003_auto_disabled_at
Create Date: 2026-10-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '004_delivery_history'
down_revision: str | None = '003_auto_disabled_at'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'webhook_delivery_logs',
        sa.Column('delivery_id', sa.String(length=36), nullable=True),
    )
    op.add_column(
        'webhook_delivery_logs',
        sa.Column('abandon_reason', sa.String(length=40), nullable=True),
    )
    op.add_column(
        'webhook_delivery_logs',
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('webhook_delivery_logs', 'last_attempt_at')
    op.drop_column('webhook_delivery_logs', 'abandon_reason')
    op.drop_column('webhook_delivery_logs', 'delivery_id')
