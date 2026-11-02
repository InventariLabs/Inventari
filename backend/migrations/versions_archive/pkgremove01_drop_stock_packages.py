"""the handling units leave, and the column that pointed at them

Revision ID: pkgremove01
Revises: svlidx01
Create Date: 2026-09-13

A handling unit — the pallet, the box, the cage a warehouse moves as one —
was modelled in ``stock_packages`` and named from every shelf row by
``stock_quants.package_id``, with no way in the product to create one. The
screens that listed them went first; the endpoint that served them
(``GET /api/v1/stock-packages``) goes with the model, and the model takes
the table with it. A table nothing writes and nothing reads is not a
feature kept in reserve: it is a column every reader of the shelf has to
step around, and a name the next reader has to check.

Dropped in the order the foreign keys demand: the constraint first, then
the column — its key ``fk_stock_quants_package_id_stock_packages`` goes
with it — then the table, which nothing else references.

The unique constraint returns without ``package_id``, ``NULLS NOT
DISTINCT`` kept because the race it guards (``quantnulls01``) is between
rows whose remaining nullable members are NULL, under a name that says
what it now spans: ``uq_quant_product_location_lot_owner``.

The downgrade rebuilds the table as the baseline built it, with the
foreign keys and the indexes the chain adds on top, and gives the column
and the six-column constraint back. The rows are not restored: nothing
could create one after the screens were removed, so the shape is all there
is to bring back.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'pkgremove01'
down_revision: str | Sequence[str] | None = 'svlidx01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT_BEFORE = 'uq_quant_product_location_lot_package'
_CONSTRAINT_AFTER = 'uq_quant_product_location_lot_owner'

#: The key the constraint spanned while it named the package.
_KEY_BEFORE = (
    'organization_id, product_template_id, storage_location_id, '
    'lot_id, package_id, owner_id'
)
_KEY_AFTER = (
    'organization_id, product_template_id, storage_location_id, '
    'lot_id, owner_id'
)

#: The foreign keys ``schemafk01`` adds to the table, spelled the way it
#: spells them — a downgrade below this revision drops them by name.
_TABLE_FOREIGN_KEYS = (
    (
        'fk_stock_packages_parent_id_stock_packages',
        'parent_id',
        'stock_packages (id)',
        '',
    ),
    (
        'fk_stock_packages_storage_location_id_storage_locations',
        'storage_location_id',
        'storage_locations (id)',
        ' ON DELETE SET NULL',
    ),
    (
        'fk_stock_packages_organization_id_organizations',
        'organization_id',
        'organizations (id)',
        ' ON DELETE CASCADE',
    ),
)


def upgrade() -> None:
    op.execute(
        f'ALTER TABLE stock_quants DROP CONSTRAINT IF EXISTS {_CONSTRAINT_BEFORE}'
    )
    op.execute(
        f'ALTER TABLE stock_quants ADD CONSTRAINT {_CONSTRAINT_AFTER} '
        f'UNIQUE NULLS NOT DISTINCT ({_KEY_AFTER})'
    )
    op.drop_column('stock_quants', 'package_id')
    op.drop_table('stock_packages')


def downgrade() -> None:
    op.create_table(
        'stock_packages',
        sa.Column('id', postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column('organization_id', postgresql.UUID(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('parent_id', postgresql.UUID()),
        sa.Column('storage_location_id', postgresql.UUID()),
        sa.Column('meta_data', postgresql.JSONB()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        'ix_stock_packages_organization_id', 'stock_packages', ['organization_id']
    )
    op.create_index('ix_stock_packages_parent_id', 'stock_packages', ['parent_id'])
    for name, column, target, ondelete in _TABLE_FOREIGN_KEYS:
        op.execute(
            f'ALTER TABLE stock_packages ADD CONSTRAINT {name} '
            f'FOREIGN KEY ({column}) REFERENCES {target}{ondelete}'
        )

    op.add_column('stock_quants', sa.Column('package_id', postgresql.UUID()))
    op.execute(
        'ALTER TABLE stock_quants ADD CONSTRAINT '
        'fk_stock_quants_package_id_stock_packages FOREIGN KEY (package_id) '
        'REFERENCES stock_packages (id) ON DELETE SET NULL'
    )
    op.execute(
        f'ALTER TABLE stock_quants DROP CONSTRAINT IF EXISTS {_CONSTRAINT_AFTER}'
    )
    op.execute(
        f'ALTER TABLE stock_quants ADD CONSTRAINT {_CONSTRAINT_BEFORE} '
        f'UNIQUE NULLS NOT DISTINCT ({_KEY_BEFORE})'
    )
