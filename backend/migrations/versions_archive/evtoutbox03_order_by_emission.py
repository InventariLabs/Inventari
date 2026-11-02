"""the outbox orders its rows by when each was written, not when its transaction began.

Revision ID: evtoutbox03
Revises: tzaware01
Create Date: 2026-10-16

``created_at`` defaulted to ``now()``, which Postgres freezes at the start of
the transaction. Every event one request wrote carried the same instant, so
the relay, which reads by ``created_at``, could publish a move's
``item.moved`` before its ``item.updated``; and a long transaction that began
first but committed last was published ahead of one that committed before it.
``clock_timestamp()`` is the moment the row is written, which is the order the
code emitted the events in.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'evtoutbox03'
down_revision: str | None = 'tzaware01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        'event_outbox',
        'created_at',
        server_default=sa.text('clock_timestamp()'),
    )


def downgrade() -> None:
    op.alter_column('event_outbox', 'created_at', server_default=sa.func.now())
