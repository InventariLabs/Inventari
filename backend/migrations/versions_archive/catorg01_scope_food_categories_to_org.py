"""move the food category seed from the installation to its organizations

Revision ID: catorg01
Revises: prgpurge01
Create Date: 2026-08-20

Data migration. Onboarding used to run the profile seed without an
owner, so a tenant picking "Food & Home" wrote 33 categories with
``organization_id IS NULL`` — and category reads surface owner-less rows to
*every* organization on the installation, neutral workspace modes included.

The seed now carries an owner. This migration repairs what the old one left
behind: each organization that chose the food profile (or that already points
at one of those rows) gets its own copy, every reference is moved onto the
copy, and the owner-less rows go away. Organizations that never asked for a
food catalogue stop seeing one.

The code list is frozen on purpose: a migration describes the rows that exist
at this revision, not the rows the seeder happens to declare later.
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = 'catorg01'
down_revision = 'prgpurge01'
branch_labels = None
depends_on = None

# app/seed_profiles/_food_home_categories_{freezer,fridge,pantry}.py @ catorg01
_FOOD_SEED_CODES = [
    'pork', 'beef', 'poultry', 'fish', 'seafood', 'frozen_meals',
    'frozen_vegetables', 'frozen_fruits', 'ice_cream', 'frozen_pizza',
    'dairy', 'cheese', 'deli', 'eggs', 'fresh_vegetables', 'fresh_fruits',
    'drinks', 'sauces', 'fresh_meat', 'fresh_meals', 'dry_products', 'pasta',
    'rice_grains', 'canned_goods', 'spices_herbs', 'oils_vinegars',
    'flours_sugars', 'snacks', 'sweets', 'beverages', 'tea_coffee',
    'cans_jars', 'other',
]  # fmt: skip

# Profiles whose seed writes the food catalogue.
_FOOD_PROFILE_IDS = ['food_home']

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
            SELECT id FROM categories
            WHERE organization_id IS NULL
              AND module_name IS NULL
              AND code = ANY(:codes)
        """),
        {'codes': _FOOD_SEED_CODES},
    ).fetchall()
    if not global_rows:
        return
    global_ids = [row[0] for row in global_rows]

    references = [
        (table, column)
        for table, column in _referencing_tables(bind)
        if _has_organization_column(bind, table)
    ]

    owner_ids = {
        row[0]
        for row in bind.execute(
            sa.text(
                'SELECT id FROM organizations WHERE active_profile_id = ANY(:profiles)'
            ),
            {'profiles': _FOOD_PROFILE_IDS},
        ).fetchall()
    }
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
            bind.execute(
                sa.text(f"""
                    INSERT INTO categories (id, organization_id, {columns})
                    SELECT :new_id, :org, {columns}
                    FROM categories WHERE id = :source
                """),  # noqa: S608 — identifiers come from _COPIED_COLUMNS
                {'new_id': uuid.uuid4(), 'org': org_id, 'source': source_id},
            )

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


def downgrade() -> None:
    # No inverse: the owner-less rows the upgrade removed cannot be told apart
    # from the per-organization copies it created, and re-sharing one
    # organization's catalogue with the whole installation is the defect this
    # revision exists to remove. Re-run the seeder to restore an
    # installation-wide catalogue if one is genuinely wanted.
    pass
