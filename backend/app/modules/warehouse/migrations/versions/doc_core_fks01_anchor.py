"""the four keys the core cannot build: core rows pointing at document rows

Revision ID: doc_core_fks01
Revises: doc_line_unit_backfill01
Create Date: 2026-09-12

Four foreign keys the models declare had nowhere to be built. The core
chain must not reach for a table a module builds, so it left them out by
name — ``items.source_document_id`` and ``item_history.source_document_id``
to ``documents``, ``stock_reservations.document_line_id`` and
``stock_valuation_layers.document_line_id`` to ``document_lines`` — and
this module's chain never picked them up. A full installation therefore
never got them: a document could be deleted out from under the records that
named it, and the ``SET NULL`` the models promise was a word without a
constraint behind it.

They belong here, because they can only exist while this module does. The
downgrade drops them for the same reason: a module whose tables are about
to go needs the keys pointing at them gone first.

Each side is guarded: a core table that is not there yet (an install order
nobody promised) is skipped rather than crashed on, and a key that already
exists — a database that grew through the archived chain — is left alone.

The rows are another matter: a database that lived with no key behind the
promise holds rows naming a document id nothing answers to, and the key
cannot be built over them — it would die as a raw foreign key violation
partway through a module upgrade. So each key counts its dangling rows
first, sets them to NULL — the same thing its ``SET NULL`` does when the
document is deleted, so the promise catches up with what the missing key
let through — reports how many, and is built validated. The sibling
``schemafk01`` leaves its orphans ``NOT VALID`` for an operator to finish;
here a reference to a document that no longer exists carries no
information, the key promises ``SET NULL`` anyway, and an upgrade that
stops mid-chain is the worse answer. Rows naming a real row pass through
untouched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_core_fks01'
down_revision: str | Sequence[str] | None = 'doc_line_unit_backfill01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (constraint, table, column, target table)
_KEYS = (
    ('fk_items_source_document_id', 'items', 'source_document_id', 'documents'),
    (
        'fk_item_history_source_document_id',
        'item_history',
        'source_document_id',
        'documents',
    ),
    (
        'fk_stock_reservations_document_line_id',
        'stock_reservations',
        'document_line_id',
        'document_lines',
    ),
    (
        'fk_stock_valuation_layers_document_line_id',
        'stock_valuation_layers',
        'document_line_id',
        'document_lines',
    ),
)


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text('SELECT to_regclass(:name)'), {'name': f'public.{name}'}
        ).scalar()
    )


def _fk_on(table: str, column: str, target: str) -> str | None:
    """The name of an existing key on this column, whatever it is called."""
    bind = op.get_bind()
    return bind.execute(
        sa.text("""
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class src ON src.oid = c.conrelid
            JOIN pg_class tgt ON tgt.oid = c.confrelid
            JOIN pg_attribute a
              ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
            WHERE c.contype = 'f'
              AND src.relname = :table
              AND tgt.relname = :target
              AND a.attname = :column
            LIMIT 1
        """),
        {'table': table, 'column': column, 'target': target},
    ).scalar()


def _orphans(table: str, column: str, target: str) -> int:
    """Rows that name a target id no row answers to."""
    counted = (
        op.get_bind()
        .execute(
            sa.text(
                f'SELECT count(*) FROM {table} child '
                f'WHERE child.{column} IS NOT NULL AND NOT EXISTS ('
                f'SELECT 1 FROM {target} parent WHERE parent.id = child.{column})'
            )
        )
        .scalar_one()
    )
    return int(counted)


def _clear_orphans(table: str, column: str, target: str) -> None:
    """NULL the dangling references a key is about to be built over."""
    op.get_bind().execute(
        sa.text(
            f'UPDATE {table} SET {column} = NULL '
            f'WHERE {column} IS NOT NULL AND NOT EXISTS ('
            f'SELECT 1 FROM {target} parent WHERE parent.id = {column})'
        )
    )


def _report_cleared(cleared: list[str]) -> None:
    print(
        f'doc_core_fks01: {len(cleared)} foreign key(s) were built over rows '
        'that named a document or a line that no longer exists. Those '
        'references were set to NULL — the same thing each key does when its '
        'target is deleted — and every key is now enforced.\n' + '\n'.join(cleared)
    )


def upgrade() -> None:
    cleared: list[str] = []
    for name, table, column, target in _KEYS:
        if not _table_exists(table) or not _table_exists(target):
            continue
        if _fk_on(table, column, target):
            continue
        orphans = _orphans(table, column, target)
        if orphans:
            _clear_orphans(table, column, target)
            cleared.append(
                f'  {table}.{column} -> {target}: {orphans} row(s) set to NULL'
            )
        op.create_foreign_key(
            name, table, target, [column], ['id'], ondelete='SET NULL'
        )
    if cleared:
        _report_cleared(cleared)


def downgrade() -> None:
    for name, table, column, target in _KEYS:
        if not _table_exists(table):
            continue
        existing = _fk_on(table, column, target)
        if existing:
            op.drop_constraint(existing, table, type_='foreignkey')
