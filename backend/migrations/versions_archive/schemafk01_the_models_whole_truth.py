"""the models' whole truth: foreign keys and the quant uniqueness

Revision ID: schemafk01
Revises: auditidx01
Create Date: 2026-09-09

``baseline_001_full_schema`` built the core with not a single foreign
key, and the later migrations added them only for their own new tables —
so a database that grew through the chain and a database that started
from the baseline were two different promises. The models cascade a
delete on ``items.organization_id``; the fresh database happily kept
the orphan. Guards built on ``IntegrityError`` never fired on it.

This migration adds what the models declare, for the tables this chain
builds, additively: each foreign key lands ``NOT VALID`` — no table
scan, no long lock on a working installation — and is validated
immediately after, which scans but only takes a light lock, wherever
the rows already agree with it (below for where they do not). Fresh
databases pay nothing either way: ``NOT VALID`` on an empty table is a
formality.

Foreign keys anchored on module tables (``documents``,
``document_lines`` — ``items.source_document_id`` and friends) are
deliberately absent: this chain must not reach for a table a module
migration builds, and a module install carries its own schema.

The unique constraints the models declare — among them
``uq_quant_product_location_lot_package``, which lived only in the
versions archive no fresh database replays — come back with their
model names, unless the database already carries them under those
names: a base with a past got them from the archive, and adding them
again would stop the replay at a duplicate object.

A database that started from the baseline and has been in use is the
population this migration is for, and on it orphans are the norm, not
an accident: without a single foreign key, deleting an organization or
a category left its children behind (measured on development databases:
seven of twenty-one, up to 5,979 orphaned rows in one column).
Validating a foreign key over them would kill the boot. So a foreign
key over orphans is left ``NOT VALID``: every new write is checked and
every cascade fires from now on, the old rows stay as they were, and
the migration prints which constraint, how many rows, the query that
shows them and the statement that finishes the job. ``db doctor``
repeats that list on every start until the constraint is validated —
``ckvalid01`` is what happens to a ``NOT VALID`` nobody is reminded of.

A unique constraint has no ``NOT VALID``, and leaving it out would
ship the installation without the guarantee the quant insert race
relies on. Duplicates are therefore counted before any DDL runs, and
if there are any the migration stops with the same kind of report
(none of the twenty-one dev databases has one).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'schemafk01'
down_revision: str | None = 'auditidx01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FOREIGN_KEYS: tuple[tuple[str, str, str, str, str | None], ...] = (
    ('organizations', 'created_by', 'users', 'id', None),
    ('users', 'organization_id', 'organizations', 'id', None),
    ('ai_usage_logs', 'user_id', 'users', 'id', 'SET NULL'),
    ('ai_usage_logs', 'organization_id', 'organizations', 'id', 'CASCADE'),
    ('audit_log', 'organization_id', 'organizations', 'id', 'CASCADE'),
    ('audit_log', 'user_id', 'users', 'id', 'SET NULL'),
    ('categories', 'organization_id', 'organizations', 'id', 'CASCADE'),
    ('document_templates', 'created_by', 'users', 'id', 'SET NULL'),
    ('document_templates', 'organization_id', 'organizations', 'id', 'CASCADE'),
    ('item_type_definitions', 'organization_id', 'organizations', 'id', 'CASCADE'),
    ('notifications', 'user_id', 'users', 'id', 'CASCADE'),
    ('partners', 'organization_id', 'organizations', 'id', 'CASCADE'),
    ('partners', 'created_by', 'users', 'id', 'SET NULL'),
    ('registration_requests', 'approved_by_id', 'users', 'id', None),
    ('roles', 'organization_id', 'organizations', 'id', None),
    ('storage_types', 'organization_id', 'organizations', 'id', None),
    ('storage_types', 'created_by', 'users', 'id', None),
    ('system_settings', 'updated_by', 'users', 'id', 'SET NULL'),
    ('uom_categories', 'organization_id', 'organizations', 'id', 'CASCADE'),
    ('organization_invitations', 'created_by', 'users', 'id', None),
    ('organization_invitations', 'organization_id', 'organizations', 'id', 'CASCADE'),
    ('storage_locations', 'parent_id', 'storage_locations', 'id', 'SET NULL'),
    ('storage_locations', 'storage_type_id', 'storage_types', 'id', None),
    ('storage_locations', 'organization_id', 'organizations', 'id', 'CASCADE'),
    ('storage_locations', 'created_by', 'users', 'id', None),
    ('uoms', 'category_id', 'uom_categories', 'id', None),
    ('uoms', 'organization_id', 'organizations', 'id', 'CASCADE'),
    ('user_roles', 'role_id', 'roles', 'id', None),
    ('user_roles', 'user_id', 'users', 'id', None),
    ('label_pool', 'organization_id', 'organizations', 'id', 'CASCADE'),
    ('label_pool', 'created_by', 'users', 'id', None),
    ('label_pool', 'item_id', 'items', 'id', 'SET NULL'),
    ('label_pool', 'target_storage_location_id', 'storage_locations', 'id', 'SET NULL'),
    ('product_templates', 'volume_uom_id', 'uoms', 'id', None),
    ('product_templates', 'uom_id', 'uoms', 'id', None),
    ('product_templates', 'organization_id', 'organizations', 'id', 'CASCADE'),
    ('product_templates', 'weight_uom_id', 'uoms', 'id', None),
    ('stock_packages', 'parent_id', 'stock_packages', 'id', None),
    ('stock_packages', 'storage_location_id', 'storage_locations', 'id', 'SET NULL'),
    ('stock_packages', 'organization_id', 'organizations', 'id', 'CASCADE'),
    ('items', 'uom_id', 'uoms', 'id', None),
    ('items', 'partner_id', 'partners', 'id', 'SET NULL'),
    ('items', 'storage_location_id', 'storage_locations', 'id', 'CASCADE'),
    ('items', 'deleted_by', 'users', 'id', None),
    ('items', 'category_id', 'categories', 'id', None),
    ('items', 'template_id', 'product_templates', 'id', None),
    ('items', 'organization_id', 'organizations', 'id', 'CASCADE'),
    ('stock_lots', 'product_template_id', 'product_templates', 'id', 'CASCADE'),
    ('stock_lots', 'organization_id', 'organizations', 'id', 'CASCADE'),
    ('item_attachments', 'item_id', 'items', 'id', 'CASCADE'),
    ('item_history', 'organization_id', 'organizations', 'id', 'CASCADE'),
    ('item_history', 'item_id', 'items', 'id', 'CASCADE'),
    ('item_history', 'user_id', 'users', 'id', 'SET NULL'),
    ('stock_quants', 'lot_id', 'stock_lots', 'id', 'SET NULL'),
    ('stock_quants', 'organization_id', 'organizations', 'id', 'CASCADE'),
    ('stock_quants', 'owner_id', 'partners', 'id', 'SET NULL'),
    ('stock_quants', 'product_template_id', 'product_templates', 'id', 'CASCADE'),
    ('stock_quants', 'storage_location_id', 'storage_locations', 'id', 'CASCADE'),
    ('stock_quants', 'package_id', 'stock_packages', 'id', 'SET NULL'),
    ('stock_valuation_layers', 'product_template_id', 'product_templates', 'id', 'CASCADE'),
    ('stock_valuation_layers', 'organization_id', 'organizations', 'id', 'CASCADE'),
)

_UNIQUE_CONSTRAINTS: tuple[tuple[str, str, str], ...] = (
    ('partners', 'organization_id, name, type', 'uq_partner_org_name_type'),
    ('uom_categories', 'organization_id, name', 'uq_uom_category_org_name'),
    ('uoms', 'organization_id, name', 'uq_uom_org_name'),
    ('stock_lots', 'organization_id, product_template_id, name', 'uq_lot_org_product_name'),
    ('stock_quants', 'organization_id, product_template_id, storage_location_id, lot_id, package_id', 'uq_quant_product_location_lot_package'),
)


def _fingerprint(table: str, column: str, target: str) -> str:
    """A constraint name nobody will collide with, stable across runs."""
    return f'fk_{table}_{column}_{target}'


def _constraint_exists(table: str, name: str) -> bool:
    """Whether the database already carries this constraint.

    A database that grew through the historical chain already holds these
    unique constraints (the archive created them under the very names the
    models declare); only the baseline-built one needs them added here.
    """
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text(
                'SELECT 1 FROM pg_constraint '
                'WHERE conname = :name AND conrelid = to_regclass(:table)'
            ),
            {'name': name, 'table': f'public.{table}'},
        ).scalar()
    )


#: Declared on the model columns (``index=True`` and explicit), never
#: built by any migration. CONCURRENTLY, so an existing installation
#: keeps writing while they build.
_MISSING_INDEXES: tuple[tuple[str, str, str], ...] = (
    ('items', 'ix_items_barcode', 'barcode'),
    ('items', 'ix_items_org_barcode_active', 'organization_id, barcode, is_deleted'),
    ('items', 'ix_items_quantity', 'quantity'),
    ('product_templates', 'ix_product_templates_barcode', 'barcode'),
    ('product_templates', 'ix_product_templates_sku', 'sku'),
    ('stock_reservations', 'ix_reservation_document', 'document_id'),
    ('stock_reservations', 'ix_reservation_quant', 'stock_quant_id'),
)


def _orphans(table: str, column: str, target: str, target_col: str) -> int:
    return op.get_bind().execute(
        sa.text(
            f'SELECT count(*) FROM {table} child '
            f'WHERE child.{column} IS NOT NULL AND NOT EXISTS ('
            f'SELECT 1 FROM {target} parent '
            f'WHERE parent.{target_col} = child.{column})'
        )
    ).scalar_one()


def _refuse_duplicates() -> None:
    """Stop before any DDL if a unique constraint cannot be built.

    Rows with a NULL in any of the columns never collide (Postgres treats
    NULLs as distinct), so only fully populated keys are counted.
    """
    problems: list[str] = []
    for table, columns, name in _UNIQUE_CONSTRAINTS:
        populated = ' AND '.join(f'{c} IS NOT NULL' for c in columns.split(', '))
        groups = op.get_bind().execute(
            sa.text(
                f'SELECT count(*) FROM (SELECT 1 FROM {table} WHERE {populated} '
                f'GROUP BY {columns} HAVING count(*) > 1) duplicate'
            )
        ).scalar_one()
        if groups:
            problems.append(
                f'  {name}: {groups} group(s) of {table} rows share '
                f'({columns})\n'
                f'    see them: SELECT {columns}, count(*) FROM {table} '
                f'WHERE {populated} GROUP BY {columns} HAVING count(*) > 1;'
            )
    if problems:
        raise RuntimeError(
            'schemafk01 stopped before changing anything: the models declare '
            'these unique constraints, and the data already breaks them.\n'
            + '\n'.join(problems)
            + '\nMerge or remove the duplicate rows, then start again — the '
            'migration reruns from the top.'
        )


def _report_unvalidated(left: list[str]) -> None:
    print(
        f'schemafk01: {len(left)} foreign key(s) left NOT VALID over rows that '
        'point at a parent that no longer exists. New writes are checked and '
        'cascades fire; the old rows are untouched.\n'
        + '\n'.join(left)
        + '\n`manage.py db doctor` lists what is still unvalidated on every start.'
    )


def upgrade() -> None:
    _refuse_duplicates()
    # One column type the models corrected: the chain built JSON, the
    # model declares JSONB (indexed containment queries). USING keeps
    # every value; on an existing installation this rewrites the table.
    op.execute(
        'ALTER TABLE storage_locations '
        'ALTER COLUMN warehouse_config TYPE JSONB '
        'USING warehouse_config::jsonb'
    )
    left: list[str] = []
    for table, column, target, target_col, ondelete in _FOREIGN_KEYS:
        name = _fingerprint(table, column, target)
        rule = f' ON DELETE {ondelete}' if ondelete else ''
        op.execute(
            f'ALTER TABLE {table} ADD CONSTRAINT {name} '
            f'FOREIGN KEY ({column}) REFERENCES {target} ({target_col})'
            f'{rule} NOT VALID'
        )
        orphans = _orphans(table, column, target, target_col)
        if orphans:
            left.append(
                f'  {table}.{column} -> {target}: {orphans} orphaned row(s)\n'
                f'    see them: SELECT * FROM {table} WHERE {column} NOT IN '
                f'(SELECT {target_col} FROM {target});\n'
                f'    then:     ALTER TABLE {table} VALIDATE CONSTRAINT {name};'
            )
        else:
            op.execute(f'ALTER TABLE {table} VALIDATE CONSTRAINT {name}')
    if left:
        _report_unvalidated(left)
    for table, columns, name in _UNIQUE_CONSTRAINTS:
        if _constraint_exists(table, name):
            continue
        op.execute(
            f'ALTER TABLE {table} ADD CONSTRAINT {name} UNIQUE ({columns})'
        )
    with op.get_context().autocommit_block():
        for table, name, columns in _MISSING_INDEXES:
            op.execute(
                f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} '
                f'ON {table} ({columns})'
            )


def downgrade() -> None:
    op.execute(
        'ALTER TABLE storage_locations '
        'ALTER COLUMN warehouse_config TYPE JSON '
        'USING warehouse_config::text::json'
    )
    with op.get_context().autocommit_block():
        for table, name, _columns in _MISSING_INDEXES:
            op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS {name}')
    for table, columns, name in reversed(_UNIQUE_CONSTRAINTS):
        op.execute(f'ALTER TABLE {table} DROP CONSTRAINT {name}')
    for table, column, target, _target_col, _ondelete in reversed(
        _FOREIGN_KEYS
    ):
        op.execute(
            f'ALTER TABLE {table} '
            f'DROP CONSTRAINT {_fingerprint(table, column, target)}'
        )

