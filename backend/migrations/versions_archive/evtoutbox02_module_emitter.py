"""the outbox remembers which module emitted the event.

Revision ID: evtoutbox02
Revises: onbmanual01
Create Date: 2026-10-04

A stream message carried the event and the node that relayed it, and the
node is a UUID — so a module's event that made a consumer fail could not be
traced back to the module. The emitter rides along in the outbox row from
the transaction that produced the event; NULL means core code, which speaks
for no module in particular. Nullable and defaultless: existing unpublished
rows relay exactly as before, with no emitter.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'evtoutbox02'
down_revision: str | None = 'onbmanual01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'event_outbox',
        sa.Column('emitter_module', sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('event_outbox', 'emitter_module')
