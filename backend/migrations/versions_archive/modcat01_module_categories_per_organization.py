"""Module-declared categories become per-organization rows.

Revision ID: modcat01
Revises: uomround01
Create Date: 2026-08-26

Data migration. Application startup used to run ``sync_categories`` for every
registered module, writing the module's declared categories with
``organization_id IS NULL`` — and category reads surface owner-less rows to
*every* organization on the installation, so a tenant in a neutral workspace
mode saw the equipment catalogue (``LAPTOP``, ``SERVER``, ...). The startup
sync is gone; ``BaseModule.system_on_enable`` seeds the declared categories
for the organization that enables the module, the same move ``catorg01``
made for the profile seed and orgsttype01 for storage types.

This migration repairs what the startup sync left behind. Every owner-less
category that carries a ``module_name`` is copied to each organization that
has the module in ``enabled_modules`` or that already points at the row,
every reference is moved onto the copy, and the owner-less rows go away —
deleted when nothing references them anymore, deactivated when a table
without an organization column still does (its rows cannot be attributed, so
the pointer is kept and the row leaves every category list instead).

The owner-less rows themselves carry the module name, so no code list is
frozen here: the migration reads the world as it is at this revision.
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = 'modcat01'
down_revision = 'uomround01'
branch_labels = None
depends_on = None

_COPIED_COLUMNS = (
    'name',
    'code',
    'category_type',
    'context_tag',
    'icon',
    'emoji',
    'color',
    'sort_order',
    'meta_data',
    'module_name',
    'is_active',
    'field_definitions',
)


def _referencing_tables(bind) -> list[tuple[str, str]]:
    """Return (table, column) pairs whose foreign key points at categories.id.

    Read from the live catalogue rather than a hand-kept list: module tables
    (shopping lists, putaway rules) exist only where their module is
    installed, and the next module to reference a category must not silently
    keep a stale pointer.
    """
    rows = bind.execute(
        sa.text("""
            SELECT tc.table_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON kcu.constraint_name = tc.constraint_name
             AND kcu.constraint_schema = tc.constraint_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.constraint_schema = tc.constraint_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = current_schema()
              AND ccu.table_name = 'categories'
              AND ccu.column_name = 'id'
        """)
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _has_organization_column(bind, table: str) -> bool:
    return bool(
        bind.execute(
            sa.text("""
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = :t AND column_name = 'organization_id'
            """),
            {'t': table},
        ).first()
    )


def upgrade() -> None:
    bind = op.get_bind()

    global_rows = bind.execute(
        sa.text("""
            SELECT id, code, module_name FROM categories
            WHERE organization_id IS NULL AND module_name IS NOT NULL
        """)
    ).fetchall()
    if not global_rows:
        return
    global_ids = [row[0] for row in global_rows]
    modules_by_id = {row[0]: row[2] for row in global_rows}

    references = [
        (table, column)
        for table, column in _referencing_tables(bind)
        if _has_organization_column(bind, table)
    ]

    owner_ids: set = set()
    orgs = bind.execute(
        sa.text('SELECT id, enabled_modules FROM organizations')
    ).fetchall()
    enabled_modules = {row[0]: set(row[1] or []) for row in orgs}
    for row in global_rows:
        for org_id, modules in enabled_modules.items():
            if row[2] in modules:
                owner_ids.add(org_id)
    for table, column in references:
        owner_ids.update(
            row[0]
            for row in bind.execute(
                sa.text(f"""
                    SELECT DISTINCT organization_id FROM {table}
                    WHERE {column} = ANY(:ids) AND organization_id IS NOT NULL
                """),  # noqa: S608 — identifiers come from the catalogue, not input
                {'ids': global_ids},
            ).fetchall()
        )

    columns = ', '.join(_COPIED_COLUMNS)
    copied = 0
    for org_id in owner_ids:
        missing = bind.execute(
            sa.text("""
                SELECT id, code FROM categories c
                WHERE c.id = ANY(:ids)
                  AND NOT EXISTS (
                      SELECT 1 FROM categories owned
                      WHERE owned.organization_id = :org AND owned.code = c.code
                  )
            """),
            {'ids': global_ids, 'org': org_id},
        ).fetchall()
        for source_id, _code in missing:
            # An organization gets the rows of the modules it enabled plus the
            # rows it already references — not another module's catalogue it
            # happens to share the installation with.
            referencing_org = modules_by_id[source_id] in enabled_modules.get(
                org_id, set()
            )
            if not referencing_org:
                pointed_at = any(
                    bind.execute(
                        sa.text(f"""
                            SELECT 1 FROM {table}
                            WHERE {column} = :source AND organization_id = :org
                            LIMIT 1
                        """),  # noqa: S608 — identifiers from the catalogue
                        {'source': source_id, 'org': org_id},
                    ).first()
                    for table, column in references
                )
                if not pointed_at:
                    continue
            bind.execute(
                sa.text(f"""
                    INSERT INTO categories (id, organization_id, {columns})
                    SELECT :new_id, :org, {columns}
                    FROM categories WHERE id = :source
                """),  # noqa: S608 — identifiers come from _COPIED_COLUMNS
                {'new_id': uuid.uuid4(), 'org': org_id, 'source': source_id},
            )
            copied += 1

    for table, column in references:
        bind.execute(
            sa.text(f"""
                UPDATE {table} AS ref
                SET {column} = owned.id
                FROM categories AS shared, categories AS owned
                WHERE ref.{column} = shared.id
                  AND shared.id = ANY(:ids)
                  AND owned.organization_id = ref.organization_id
                  AND owned.code = shared.code
            """),  # noqa: S608 — identifiers come from the catalogue, not input
            {'ids': global_ids},
        )

    still_referenced: set = set()
    for table, column in _referencing_tables(bind):
        still_referenced.update(
            row[0]
            for row in bind.execute(
                sa.text(f"""
                    SELECT DISTINCT {column} FROM {table}
                    WHERE {column} = ANY(:ids)
                """),  # noqa: S608 — identifiers come from the catalogue, not input
                {'ids': global_ids},
            ).fetchall()
        )

    # A row nothing points at goes; one that is still referenced (a table
    # without an organization column, so its rows cannot be attributed) is
    # deactivated instead, which takes it out of every category list without
    # breaking the pointer.
    removable = [cid for cid in global_ids if cid not in still_referenced]
    if removable:
        bind.execute(
            sa.text('DELETE FROM categories WHERE id = ANY(:ids)'),
            {'ids': removable},
        )
    orphaned = [cid for cid in global_ids if cid in still_referenced]
    if orphaned:
        bind.execute(
            sa.text('UPDATE categories SET is_active = false WHERE id = ANY(:ids)'),
            {'ids': orphaned},
        )

    print(
        f'modcat01: copied {copied} module categories to {len(owner_ids)} '
        f'organizations, removed {len(removable)} global rows, '
        f'deactivated {len(orphaned)} still-referenced ones'
    )


def downgrade() -> None:
    # No inverse: the owner-less rows the upgrade removed cannot be told apart
    # from the per-organization copies it created, and re-sharing one
    # organization's catalogue with the whole installation is the defect this
    # revision exists to remove. Re-enable the module to restore its
    # categories for an organization if one is genuinely wanted.
    pass
