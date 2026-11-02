"""maker module — number the production orders 009 left NULL.

009's docstring declined a backfill: a number the row never had is not
invented afterwards. That decision was reversed on 2026-08-29 — every
production order must carry a number a
person can say out loud, including the rows created before 009. Each NULL
row now receives the number it would have been issued, computed the way
``production_service._next_order_number`` computes one at creation: the
year comes from the row's own ``created_at`` (UTC), the per-(organization,
year) sequence continues after the highest ``PR/{year}/`` number already in
use — so numbers issued at creation are never reused or collided with —
and NULL rows are numbered in ``created_at`` order with ``id`` as a stable
tiebreak for identical stamps.

Downgrade: nothing to undo. The backfilled numbers are indistinguishable
from the ones orders have received at creation since 009, so a reversal
could only null numbers wholesale — erasing issued numbers the backfill
never touched. The column, and every number with it, is dropped by 009's
downgrade. The unique index stays exactly as 009 created it.

Revision ID: 011_backfill_order_numbers
Revises: 010_add_short_at_create
Create Date: 2026-08-29
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = '011_backfill_order_numbers'
down_revision: str | None = '010_add_short_at_create'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _utc_year(created_at: datetime) -> int:
    """Year the row was created, in UTC — ``created_at`` is a timestamptz."""
    if created_at.tzinfo is None:
        return created_at.year
    return created_at.astimezone(UTC).year


def _next_seq(bind: Connection) -> dict[tuple[UUID, int], int]:
    """First free sequence per (organization_id, year), mirroring the runtime.

    ``_next_order_number`` anchors to the highest numeric suffix actually in
    use for the ``PR/{year}/`` prefix — an admin-deleted row cannot reopen an
    old number — and legacy NULLs never hold the sequence. The same scan here
    means the backfill never reuses or collides with a number issued at
    creation; a number that does not parse holds none, exactly as at runtime.
    """
    highest: dict[tuple[UUID, int], int] = {}
    rows = bind.execute(
        sa.text(
            'SELECT organization_id, number FROM maker_production_orders '
            "WHERE number LIKE 'PR/%'"
        )
    ).fetchall()
    for org_id, number in rows:
        parts = number.split('/')
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
            continue
        key = (org_id, int(parts[1]))
        highest[key] = max(highest.get(key, 0), int(parts[2]))
    return {key: seq + 1 for key, seq in highest.items()}


def _run_backfill(bind: Connection) -> None:
    next_seq = _next_seq(bind)
    rows = bind.execute(
        sa.text(
            'SELECT id, organization_id, created_at '
            'FROM maker_production_orders '
            'WHERE number IS NULL '
            'ORDER BY created_at, id'
        )
    ).fetchall()
    for row_id, org_id, created_at in rows:
        year = _utc_year(created_at)
        key = (org_id, year)
        seq = next_seq.get(key, 1)
        next_seq[key] = seq + 1
        bind.execute(
            sa.text(
                'UPDATE maker_production_orders SET number = :number WHERE id = :id'
            ),
            {'number': f'PR/{year}/{seq:04d}', 'id': row_id},
        )


def upgrade() -> None:
    _run_backfill(op.get_bind())


def downgrade() -> None:
    # Nothing to undo — see the module docstring.
    pass
