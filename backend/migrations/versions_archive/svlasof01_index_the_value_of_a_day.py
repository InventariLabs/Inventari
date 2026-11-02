"""index the as-of valuation on the date it cuts and orders by

Revision ID: svlasof01
Revises: tplpcs01
Create Date: 2026-09-13

The valuation of a day asks one organization's cost layers for everything up
to a date and in date order, three times over: the receipts it replays, the
count of the layers a foreign currency dropped, and the outflow total. The
date a layer is *about* is ``document_date`` falling back to its write date,
and that fallback is written out in UTC — the expression exactly as
``app.models.stock_valuation_layer.LAYER_DATED_AT_SQL`` defines it, and as the
index the model declares holds it. A cast that read the session's ``TimeZone``
would be only STABLE and could not be indexed at all, which is why the reader
and this index both name the zone.

Without one index over the whole expression the database reads the
organization's entire cost history and sorts it in memory to answer a single
day, and the report exists so an accountant can ask about many days. Every
column of the index is a key column rather than a covering inclusion: the
ordered read has to be answered by the index alone, down to the ``id`` the
ordering ends on.

Built CONCURRENTLY inside an autocommit block, following the journal's index
migration: the ledger is written on every receipt, pick and correction, and
the non-concurrent form would hold a write lock on it for the length of the
build — meaning nobody could receive or issue anything meanwhile. The
valuation layers of an established instance are the second-largest ledger
here, and nothing prunes them: whatever the build costs today, next year's
table pays more.
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'svlasof01'
down_revision: str | None = 'tplpcs01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = 'ix_svl_org_direction_dated_at'

#: The expression the index stores — the model's ``LAYER_DATED_AT_SQL``,
#: character for character. Written out here rather than imported: a migration
#: has to keep building the index it built, whatever the model says later.
_DATED_AT = "coalesce(document_date, (created_at AT TIME ZONE 'UTC')::date)"


def _drop_if_invalid(conn) -> None:
    """Remove a leftover INVALID index from an interrupted concurrent build.

    CREATE INDEX CONCURRENTLY is not transactional: interrupted, it leaves an
    index that exists but cannot be used, and ``IF NOT EXISTS`` would then
    keep it that way forever. Dropping it first is what makes a re-run of
    this migration actually repair the schema.
    """
    invalid = conn.exec_driver_sql(
        'SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid '
        'WHERE c.relname = %s AND i.indisvalid = false',
        (_INDEX,),
    ).fetchone()
    if invalid:
        conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}')


def upgrade() -> None:
    with op.get_context().autocommit_block():
        conn = op.get_bind()
        _drop_if_invalid(conn)
        conn.exec_driver_sql(
            f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} '
            'ON stock_valuation_layers '
            f'(organization_id, direction, {_DATED_AT}, created_at, id)'
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.get_bind().exec_driver_sql(f'DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}')
