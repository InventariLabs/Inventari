"""bulk packaging stops converting: one category per packaging unit

Revision ID: uomlabel01
Revises: svlbasis01
Create Date: 2026-08-29

``pack``, ``can``, ``bottle``, ``box`` and ``bag`` sat beside ``pcs`` in the
Unit category at factor 1.0, so "100 pack → 100 pcs" came back as a
successful conversion — with a confidence no unit table can have, because
the ratio of packaging to contents belongs to the product (Odoo's
``product.packaging``, which this app does not model yet). Each packaging
unit now moves into its own single-unit category: the category rule is the
one gate every conversion path reads, so pack↔pcs refuses instead of
quietly equating.

Only system rows move — the seeded catalogue. A unit an organization
created itself keeps its category. The flag is set after the move because
``uq_uom_category_reference`` allows a single reference per category and is
checked row by row. Downgrade moves the rows back to Unit and drops the
categories it created.
"""

import sqlalchemy as sa
from alembic import op

revision = 'uomlabel01'
down_revision = 'svlbasis01'
branch_labels = None
depends_on = None

# (category name, unit symbol) — the seed names the unit after the category.
PACKAGING = (
    ('Pack', 'pack'),
    ('Can', 'can'),
    ('Bottle', 'bottle'),
    ('Box', 'box'),
    ('Bag', 'bag'),
)

_FIND_REUSABLE_CATEGORY = """
    SELECT id
      FROM uom_categories c
     WHERE c.name = :name
       AND c.organization_id IS NULL
       AND NOT EXISTS (
           SELECT 1 FROM uoms u
            WHERE u.category_id = c.id AND u.symbol <> :symbol
       )
     LIMIT 1
"""

_INSERT_CATEGORY = """
    INSERT INTO uom_categories (id, name)
    SELECT gen_random_uuid(), :name
    RETURNING id
"""

_CLEAR_CATEGORY_REFERENCE = """
    UPDATE uoms SET is_reference = FALSE WHERE category_id = :category_id
"""

_MOVE_UOM = """
    UPDATE uoms
       SET category_id = :category_id
     WHERE symbol = :symbol
       AND organization_id IS NULL
       AND is_system IS TRUE
"""

_SET_REFERENCE = """
    UPDATE uoms
       SET is_reference = TRUE
     WHERE category_id = :category_id
       AND organization_id IS NULL
       AND name = :name
"""

_UNIT_CATEGORY_ID = """
    SELECT id FROM uom_categories
     WHERE name = 'Unit' AND organization_id IS NULL
     LIMIT 1
"""

_BACK_TO_UNIT = """
    UPDATE uoms
       SET category_id = :category_id, is_reference = FALSE
     WHERE symbol = :symbol
       AND organization_id IS NULL
       AND is_system IS TRUE
"""

_DROP_EMPTY_CATEGORY = """
    DELETE FROM uom_categories c
     WHERE c.name = :name
       AND c.organization_id IS NULL
       AND NOT EXISTS (SELECT 1 FROM uoms u WHERE u.category_id = c.id)
"""


def upgrade() -> None:
    conn = op.get_bind()
    moved = 0
    for name, symbol in PACKAGING:
        category_id = conn.execute(
            sa.text(_FIND_REUSABLE_CATEGORY), {'name': name, 'symbol': symbol}
        ).scalar()
        if category_id is None:
            category_id = conn.execute(
                sa.text(_INSERT_CATEGORY), {'name': name}
            ).scalar()
        # The reference flag is cleared before rows arrive, never after: the
        # per-category uniqueness is checked row by row (uomround01).
        conn.execute(
            sa.text(_CLEAR_CATEGORY_REFERENCE), {'category_id': str(category_id)}
        )
        result = conn.execute(
            sa.text(_MOVE_UOM),
            {'category_id': str(category_id), 'symbol': symbol},
        )
        moved += result.rowcount or 0
        conn.execute(
            sa.text(_SET_REFERENCE),
            {'category_id': str(category_id), 'name': name},
        )
    print(f'uomlabel01: moved {moved} packaging units out of the Unit category')


def downgrade() -> None:
    conn = op.get_bind()
    unit_id = conn.execute(sa.text(_UNIT_CATEGORY_ID)).scalar()
    if unit_id is not None:
        for _name, symbol in PACKAGING:
            conn.execute(
                sa.text(_BACK_TO_UNIT),
                {'category_id': str(unit_id), 'symbol': symbol},
            )
    for name, _symbol in PACKAGING:
        conn.execute(sa.text(_DROP_EMPTY_CATEGORY), {'name': name})
