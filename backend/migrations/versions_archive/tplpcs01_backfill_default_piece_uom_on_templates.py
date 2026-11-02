"""backfill product_templates.uom_id with the piece unit

Revision ID: tplpcs01
Revises: quantnulls01
Create Date: 2026-09-12

``uompcs01`` gave the items that predate the piece default the
answer the service gives a new one, and left ``product_templates`` out. A
template is the row the rest of the app reads — the BoM convertibility guard
and the stock screen both take the unit from it — so a template without one
silences the guard and shows "—" where the stock would say what is counted.
The service now resolves a unit on every door that mints a template; this
migration gives the rows that predate the default the same answer.

Which row that answer is follows the resolver rather than ``uompcs01``'s
narrower query: the organization's own ``pcs`` row wins, and the system row
(``organization_id IS NULL``) is the fallback. A tenant that keeps its own
piece unit keeps its rounding with it, so the backfilled rows and the rows
minted tomorrow are counted in the same step. Both tables of the catalogue
are read; neither is written.

One direction only: afterwards a defaulted row and a row where someone chose
pieces are indistinguishable, so ``downgrade`` is a documented no-op — the
same contract as ``uompcs01`` and ``011_backfill_order_numbers``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'tplpcs01'
down_revision: str | Sequence[str] | None = 'quantnulls01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _run_backfill(bind: sa.engine.interfaces.Connectable) -> None:
    """Fill every unitless template with the piece unit its tenant would get.

    Its own function so the test can run it against the suite's database,
    which is already at head (alembic would skip an upgrade it has run).
    ``bind`` is an ``Engine`` when a test hands it one and a live
    ``Connection`` when alembic does; the engine has no ``execute`` of its
    own in SQLAlchemy 2.0, so the two are adapted here rather than at each
    call site.
    """
    statement = sa.text(
        """
        UPDATE product_templates t
           SET uom_id = (
               SELECT u.id
                 FROM uoms u
                WHERE u.symbol = 'pcs'
                  AND (
                      u.organization_id = t.organization_id
                      OR u.organization_id IS NULL
                  )
                ORDER BY u.organization_id IS NULL
                LIMIT 1
           )
         WHERE t.uom_id IS NULL
        """
    )
    if isinstance(bind, sa.engine.Engine):
        with bind.begin() as conn:
            conn.execute(statement)
        return
    bind.execute(statement)


def upgrade() -> None:
    _run_backfill(op.get_bind())


def downgrade() -> None:
    # A backfilled row and a deliberately-pieces row are indistinguishable;
    # un-setting both would destroy a choice. No-op, by design.
    pass
