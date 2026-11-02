"""The pre-release legacy columns and reason values leave

Revision ID: legacyvals01
Revises: imgkey01
Create Date: 2026-10-23

Three pieces of schema existed only so that a database written before the
first release kept reading. After the release each of them would need a
deprecation window and a removal release, and a module installed from outside
could have started depending on it; before the release they simply go.

``categories.category_type`` held the food profile's FREEZER / FRIDGE /
PANTRY codes. ``context_tag`` says who owns a category and ``group_label``
says how the organisation groups it, so no read has needed the column since
the seeds stopped filling it. It is dropped here.

``shopping_lists.is_active`` duplicated the ``status`` state machine and is
owned by the shopping_lists module, so its drop ships with that module's
chain (``006_status_is_the_only_state``) rather than here.

The ``CONSUMED`` / ``DISCARDED`` vocabulary sat in three columns written by
the item flows: ``items.deletion_reason``, ``item_history.action`` and
``stock_valuation_layers.reason``, and in the reason a history row kept
beside its action. The neutral ``USED`` / ``DISPOSED`` pair has been what new
writes emit since ADR-011, and the reports read both. The rows a pre-release
database holds are rewritten to the neutral pair so one vocabulary is stored
and read from here on. Stored audit text that merely mentions a reason — the
audit log's snapshots and webhook deliveries — is left alone: those rows
record what was said at the time.

The downgrade restores the dropped column empty and leaves the neutral values
in place. Which rows carried the legacy spelling is not recoverable, and
mapping every USED back to CONSUMED would rewrite rows that were always
neutral.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = 'legacyvals01'
down_revision: str | None = 'imgkey01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Each statement maps the food-era aliases to USED / DISPOSED, whatever
#: their casing. The history rows were written uppercase; a deletion reason
#: that reached the database from an older form could have come in lowercase.
#: The comparison uppercases and the stored value is written in the
#: vocabulary's own uppercase.
_REWRITE_STATEMENTS = (
    'UPDATE items SET deletion_reason = CASE upper(deletion_reason) '
    "WHEN 'CONSUMED' THEN 'USED' "
    "WHEN 'DISCARDED' THEN 'DISPOSED' "
    'ELSE deletion_reason END '
    "WHERE upper(deletion_reason) IN ('CONSUMED', 'DISCARDED')",
    'UPDATE item_history SET action = CASE upper(action) '
    "WHEN 'CONSUMED' THEN 'USED' "
    "WHEN 'DISCARDED' THEN 'DISPOSED' "
    'ELSE action END '
    "WHERE upper(action) IN ('CONSUMED', 'DISCARDED')",
    'UPDATE stock_valuation_layers SET reason = CASE upper(reason) '
    "WHEN 'CONSUMED' THEN 'USED' "
    "WHEN 'DISCARDED' THEN 'DISPOSED' "
    'ELSE reason END '
    "WHERE upper(reason) IN ('CONSUMED', 'DISCARDED')",
    # The history row keeps the reason the person gave beside the action. A
    # row whose reason was the same food-era word would otherwise still read
    # CONSUMED in the timeline after its action says USED.
    'UPDATE item_history SET changes = jsonb_set('
    "changes::jsonb, '{reason}', to_jsonb(CASE lower(changes->>'reason') "
    "WHEN 'consumed' THEN 'USED' WHEN 'discarded' THEN 'DISPOSED' END))::json "
    "WHERE jsonb_typeof(changes::jsonb) = 'object' "
    "AND lower(changes->>'reason') IN ('consumed', 'discarded')",
)


def rewrite_reason_values(connection: Connection) -> None:
    """Move every stored food-era reason onto the neutral vocabulary."""
    for statement in _REWRITE_STATEMENTS:
        connection.execute(sa.text(statement))


def upgrade() -> None:
    # ``op.execute`` rather than a connection, so ``--sql`` mode can print the
    # same statements. ``IF EXISTS`` covers a database whose schema is already
    # at this revision (the doctor's "schema ahead" state): the column is gone
    # and the data it carried was rewritten the first time.
    for statement in _REWRITE_STATEMENTS:
        op.execute(statement)
    op.execute('ALTER TABLE categories DROP COLUMN IF EXISTS category_type')


def downgrade() -> None:
    op.add_column(
        'categories',
        sa.Column('category_type', sa.String(50), nullable=True),
    )
