"""one row per lotless quant: NULLS NOT DISTINCT and the consignor in the key

Revision ID: quantnulls01
Revises: schemafk01
Create Date: 2026-09-12

``uq_quant_product_location_lot_package`` spans two nullable columns, and
every quant a plain receipt creates has NULL in both. Under the default
NULLS DISTINCT such rows never collide, so the race guard in
``increment_quant_async`` — SELECT FOR UPDATE (which locks nothing when the
row does not exist), INSERT, and let the loser retry on IntegrityError —
had nothing to lose to. Two workers, or one double-clicked scan, left two
rows for one product on one shelf; every reader takes ``.first()``, and the
six-hourly reconciliation reported a drift it could not attribute.

The constraint comes back with NULLS NOT DISTINCT and with ``owner_id`` in
the key: consignment stock standing next to the organization's own stock of
the same product is two rows on purpose, and the stricter NULL rule would
otherwise refuse the second one.

Existing duplicates are merged before the constraint is built, not refused:
they are not a data-entry mistake the operator can be asked to resolve by
hand but the recorded output of this very bug, and their sum is the stock
that is actually on the shelf — as quants. The merge folds quantity and
reserved quantity into the oldest row of each group, moves any reservation
standing on a row it deletes onto that group's keeper first, and deletes the
rest, printing what it does. The move is the difference between stock
somebody still holds and stock blocked with no record: ``stock_reservations``
cascades from ``stock_quants``, so the delete would take the record and leave
its quantity inside ``reserved_quantity`` with nothing left that could
release it.

``items.quantity`` is a separate cache, and an item shares its quant with
other items, so there is no per-item number for the merge to recompute from a
group. Where the same race left the cache behind,
``GET /api/v1/stats/reconciliation`` names the drift (the scheduled
reconciliation run alerts on it) and a stock take corrects the count. A
database that already ran an earlier build of this migration can name what
that build dropped the same way: a quant whose ``reserved_quantity`` exceeds
the reservations against it is stock blocked with no record to release it
(``manage.py db check-reservations`` lists them).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'quantnulls01'
down_revision: str | Sequence[str] | None = 'schemafk01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEY = (
    'organization_id, product_template_id, storage_location_id, '
    'lot_id, package_id, owner_id'
)
_CONSTRAINT = 'uq_quant_product_location_lot_package'

# One ranking of every quant by its key, with the oldest row of a group as
# the keeper the others fold into. Every statement below reads the same
# window, so the keeper a reservation is moved onto is the keeper the
# quantities are folded into and the keeper that survives the delete — one
# ranking, one answer.
_RANKED = f"""
    WITH ranked AS (
        SELECT id,
               first_value(id) OVER w AS keeper,
               quantity,
               reserved_quantity
        FROM stock_quants
        WINDOW w AS (
            PARTITION BY {_KEY}
            ORDER BY created_at NULLS LAST, id
        )
    )"""


def _merge_duplicates(bind: sa.Connection) -> None:
    """Fold each group of duplicate quants into its oldest row.

    Reservations standing on a row that is about to be deleted move onto
    the group's keeper first: ``stock_reservations.stock_quant_id``
    cascades, so the delete would take the record and leave its quantity
    inside ``reserved_quantity`` with nothing left that could release it.
    """
    groups = bind.execute(
        sa.text(
            f'SELECT count(*) FROM (SELECT 1 FROM stock_quants '
            f'GROUP BY {_KEY} HAVING count(*) > 1) duplicate'
        )
    ).scalar_one()
    if not groups:
        return

    stranded_rows, stranded_quantity = bind.execute(
        sa.text(
            f"""
            {_RANKED}
            SELECT count(*), coalesce(sum(r.quantity), 0)
            FROM stock_reservations r
            JOIN ranked ON ranked.id = r.stock_quant_id
            WHERE ranked.id <> ranked.keeper
            """
        )
    ).one()

    print(
        f'quantnulls01: merging {groups} group(s) of duplicate quants — '
        'the recorded output of the race this migration closes.'
    )
    if stranded_rows:
        print(
            f'quantnulls01: {stranded_rows} reservation row(s) holding '
            f'{stranded_quantity} stand on rows this merge deletes; moving '
            'them to the surviving row first — stock_reservations cascades, '
            'so deleting first would leave that quantity blocked with no '
            'record that could release it.'
        )
    print(
        'quantnulls01: the merged sums are the shelf truth for the quants; '
        'items.quantity is a separate cache this merge does not recompute, '
        'so where the same race left it behind the drift stays — '
        'GET /api/v1/stats/reconciliation names it and the scheduled run '
        'alerts on it, then a stock take corrects the count.'
    )

    bind.execute(
        sa.text(
            f"""
            {_RANKED}
            UPDATE stock_reservations r
            SET stock_quant_id = ranked.keeper
            FROM ranked
            WHERE r.stock_quant_id = ranked.id
              AND ranked.id <> ranked.keeper
            """
        )
    )
    bind.execute(
        sa.text(
            f"""
            {_RANKED},
            folded AS (
                SELECT keeper,
                       sum(quantity) AS quantity,
                       sum(reserved_quantity) AS reserved_quantity
                FROM ranked
                GROUP BY keeper
                HAVING count(*) > 1
            )
            UPDATE stock_quants q
            SET quantity = folded.quantity,
                reserved_quantity = folded.reserved_quantity
            FROM folded
            WHERE q.id = folded.keeper
            """
        )
    )
    bind.execute(
        sa.text(
            f"""
            {_RANKED}
            DELETE FROM stock_quants q
            USING ranked
            WHERE q.id = ranked.id AND ranked.id <> ranked.keeper
            """
        )
    )


def upgrade() -> None:
    _merge_duplicates(op.get_bind())
    op.execute(f'ALTER TABLE stock_quants DROP CONSTRAINT IF EXISTS {_CONSTRAINT}')
    op.execute(
        f'ALTER TABLE stock_quants ADD CONSTRAINT {_CONSTRAINT} '
        f'UNIQUE NULLS NOT DISTINCT ({_KEY})'
    )


def downgrade() -> None:
    op.execute(f'ALTER TABLE stock_quants DROP CONSTRAINT IF EXISTS {_CONSTRAINT}')
    op.execute(
        f'ALTER TABLE stock_quants ADD CONSTRAINT {_CONSTRAINT} '
        'UNIQUE (organization_id, product_template_id, storage_location_id, '
        'lot_id, package_id)'
    )
