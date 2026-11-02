"""index the organization journal by target type, and by its full sort order

Revision ID: auditidx02
Revises: histidx01
Create Date: 2026-10-07

Three reads of the journal had no index to lean on once it was narrowed to one
kind of thing: the page filtered by type read the organization's timeline until
it had collected enough matches (most of it, for a rare type), the count under
that filter scanned the table sequentially, and the list of types the screen
offers read every row of the organization's journal on each visit. One index on
``(organization_id, target_type, created_at DESC, id)`` serves all three.

The journal now pages by the last entry seen, and a page that starts inside a
group of entries sharing one instant (a batch writes its rows together) reads
the rest of that group in id order. That is a seek only on an index that ends
in the id, so the journal's own-order index gains the id too: the new
``(organization_id, created_at DESC, id)`` replaces ``ix_audit_log_org_created_at``,
which is its prefix and so no longer earns its write cost. The single-column
``ix_audit_log_created_at`` goes too: nothing reads the journal by date without
an organization, and it was worse than idle. For the page of older entries
(``organization_id = ? AND created_at < ? ORDER BY created_at DESC, id``) the
planner, depending on its sample, walked it backward and filtered out the other
tenants' entries one by one (52,000 rows read to return a page of 100), because
the organization is a constant of the query and a constant cannot be put in the
order to rule that index out. The journal ends up with the same number of
indexes it had before this migration.

Built CONCURRENTLY inside an autocommit block, following the journal's earlier
index migration: the non-concurrent form would hold a write lock on the journal
for the length of the build.
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = 'auditidx02'
down_revision: str | None = 'histidx01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BY_TYPE = 'ix_audit_log_org_type_created_at'
_BY_ORDER = 'ix_audit_log_org_created_at_id'
_OLD_BY_ORDER = 'ix_audit_log_org_created_at'
_BY_DATE = 'ix_audit_log_created_at'


def _drop_if_invalid(conn, name: str) -> None:
    """Remove a leftover INVALID index from an interrupted concurrent build.

    CREATE INDEX CONCURRENTLY is not transactional: interrupted, it leaves an
    index that exists but cannot be used, and ``IF NOT EXISTS`` would then keep
    it that way forever. Dropping it first is what makes a re-run of this
    migration actually repair the schema.
    """
    invalid = conn.exec_driver_sql(
        'SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid '
        'WHERE c.relname = %s AND i.indisvalid = false',
        (name,),
    ).fetchone()
    if invalid:
        conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY IF EXISTS {name}')


def _create(name: str, columns: str) -> None:
    # Offline mode writes the script and has no database to ask, so the
    # leftover check is an online step only; the statements go through
    # ``op.execute``, which both modes understand.
    if not context.is_offline_mode():
        _drop_if_invalid(op.get_bind(), name)
    # DESC is written down rather than left to a backward scan, matching the
    # order the journal page asks for exactly.
    op.execute(
        f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON audit_log ({columns})'
    )


def upgrade() -> None:
    with op.get_context().autocommit_block():
        _create(_BY_TYPE, 'organization_id, target_type, created_at DESC, id')
        _create(_BY_ORDER, 'organization_id, created_at DESC, id')
        op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS {_OLD_BY_ORDER}')
        op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS {_BY_DATE}')


def downgrade() -> None:
    with op.get_context().autocommit_block():
        _create(_OLD_BY_ORDER, 'organization_id, created_at DESC')
        _create(_BY_DATE, 'created_at')
        op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS {_BY_ORDER}')
        op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS {_BY_TYPE}')
