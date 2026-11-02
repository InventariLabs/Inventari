"""shopping lists take their state from status alone

Revision ID: 006_status_is_the_only_state
Revises: 005_timestamps_carry_their_zone
Create Date: 2026-10-23

``shopping_lists.is_active`` was the pre-state-machine answer to "is this
list still shown" and then sat beside ``status`` as a second, disagreeing
copy: a client could clear one and not the other, and a list hidden by
``is_active`` could still read ``active``. The module now reads and writes
``status`` only, so the column goes.

A list that was hidden by ``is_active = false`` but still said ``active``
would reappear the moment the filter moved to ``status``. Those rows become
``archived`` — the state that means the list left every screen — and keep
their original ``updated_at`` as the moment they were archived.

The downgrade brings the column back with the value ``status`` already says,
so a database that goes back a revision is not suddenly showing lists it had
archived.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = '006_status_is_the_only_state'
down_revision: str | None = '005_timestamps_carry_their_zone'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Guarded so the statement also runs where the schema is already past this
#: revision (the doctor's "schema ahead" state); there is no work left there.
_ARCHIVE_HIDDEN = (
    'DO $$ BEGIN '
    'IF EXISTS (SELECT 1 FROM information_schema.columns '
    "WHERE table_schema = current_schema() AND table_name = 'shopping_lists' "
    "AND column_name = 'is_active') THEN "
    "UPDATE shopping_lists SET status = 'archived', "
    'archived_at = COALESCE(archived_at, updated_at) '
    "WHERE is_active IS FALSE AND status = 'active'; "
    'END IF; END $$'
)


def archive_lists_hidden_by_is_active(connection: Connection) -> None:
    """Archive the lists only ``is_active`` kept off the screens."""
    connection.execute(sa.text(_ARCHIVE_HIDDEN))


def upgrade() -> None:
    # ``op.execute`` rather than a connection, so ``--sql`` mode can print the
    # same statements.
    op.execute(_ARCHIVE_HIDDEN)
    # Postgres drops an index on a column along with the column itself.
    op.execute('ALTER TABLE shopping_lists DROP COLUMN IF EXISTS is_active')


def downgrade() -> None:
    op.add_column(
        'shopping_lists',
        sa.Column(
            'is_active',
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.execute(sa.text("UPDATE shopping_lists SET is_active = (status <> 'archived')"))
    op.alter_column('shopping_lists', 'is_active', server_default=None)
    op.create_index('ix_shopping_lists_is_active', 'shopping_lists', ['is_active'])
