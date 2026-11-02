"""restore trigram indexes for ILIKE search

The GIN/pg_trgm indexes were introduced in
``versions_archive/a1b2c3d4e5f6_add_trigram_indexes_for_ilike_search.py`` and
lost when the active chain was squashed, so every fresh install runs the item
search (``items/_list.py`` — ILIKE '%…%' over four columns) as a sequential
scan. Restoring them here also removes the performance drift between instances
migrated before the squash and instances created after it.

Built CONCURRENTLY inside an autocommit block: CREATE INDEX CONCURRENTLY cannot
run in alembic's default transaction, and the non-concurrent form would hold a
write lock on ``items`` for the length of the build.

Revision ID: trgmidx01
Revises: emailjobs01
Create Date: 2026-08-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'trgmidx01'
down_revision: str | None = 'emailjobs01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (index name, table, column) — mirrors the archived migration.
_TRIGRAM_INDEXES: tuple[tuple[str, str, str], ...] = (
    ('ix_items_name_trgm', 'items', 'name'),
    ('ix_items_barcode_trgm', 'items', 'barcode'),
    ('ix_items_brand_trgm', 'items', 'brand'),
    ('ix_items_label_code_trgm', 'items', 'label_code'),
    ('ix_product_templates_name_trgm', 'product_templates', 'name'),
    ('ix_product_templates_sku_trgm', 'product_templates', 'sku'),
    ('ix_partners_name_trgm', 'partners', 'name'),
)


def _drop_if_invalid(conn, index_name: str) -> None:
    """Remove a leftover INVALID index from an interrupted concurrent build.

    CREATE INDEX CONCURRENTLY is not transactional: if it is interrupted it
    leaves an index that is present but unusable, and ``IF NOT EXISTS`` then
    silently keeps it that way. Dropping it first is what makes a re-run of this
    migration actually repair the schema.
    """
    invalid = conn.exec_driver_sql(
        'SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid '
        "WHERE c.relname = %s AND i.indisvalid = false",
        (index_name,),
    ).fetchone()
    if invalid:
        conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY IF EXISTS {index_name}')


def upgrade() -> None:
    with op.get_context().autocommit_block():
        conn = op.get_bind()
        conn.exec_driver_sql('CREATE EXTENSION IF NOT EXISTS pg_trgm')

        for index_name, table, column in _TRIGRAM_INDEXES:
            _drop_if_invalid(conn, index_name)
            conn.exec_driver_sql(
                f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name} '
                f'ON {table} USING gin ({column} gin_trgm_ops)'
            )


def downgrade() -> None:
    # The extension itself stays: other objects may depend on it, and dropping
    # it is not what "undo these indexes" means.
    with op.get_context().autocommit_block():
        conn = op.get_bind()
        for index_name, _table, _column in reversed(_TRIGRAM_INDEXES):
            conn.exec_driver_sql(f'DROP INDEX CONCURRENTLY IF EXISTS {index_name}')
