"""Label short_code unique per organization instead of globally.

Revision ID: orglabel01
Revises: aiconn02
Create Date: 2026-07-23

Allows two SaaS tenants to reuse the same short_code (e.g. equipment serial
"DELL-1") by switching uniqueness from a global unique index on short_code to
a composite (organization_id, short_code) unique constraint. Existing food
labels (STM-XXXX) are globally unique today, so they remain valid under the
new per-org rule — no data backfill is needed.

Note: Item.label_code previously declared a ForeignKey to label_pool.short_code
(name='fk_items_label_code'). That constraint WAS created by the archived
migration 13bf636715bf_add_label_pool on databases that ran the full migration
chain, but is absent on DBs rebuilt from baseline_001_full_schema (dev). It
must be dropped here (idempotently) before dropping the index it depends on,
otherwise PostgreSQL raises DependentObjectsStillExist. The model declaration
is removed in code; integrality is enforced in the app layer (label API is the
sole writer of item.label_code).
"""

import sqlalchemy as sa
from alembic import op  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = 'orglabel01'
down_revision: str | None = 'aiconn02'
branch_labels: str | None = None
depends_on: str | None = None

_TABLE = 'label_pool'


def _index_exists(index_name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text('SELECT to_regclass(:t)'),
            {'t': f'public.{index_name}'},
        ).scalar()
    )


def _constraint_exists(constraint_name: str, table: str = _TABLE) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            'SELECT 1 FROM pg_constraint '
            'WHERE conname = :c AND conrelid = to_regclass(:t)'
        ),
        {'c': constraint_name, 't': f'public.{table}'},
    ).first()
    return row is not None


def upgrade() -> None:
    # Drop the legacy FK items.label_code -> label_pool.short_code first. It
    # depends on ix_label_pool_short_code and blocks the index drop below on
    # databases that ran the full migration chain (prod). Absent on dev DBs
    # rebuilt from baseline, so the check is idempotent.
    if _constraint_exists('fk_items_label_code', table='items'):
        op.drop_constraint('fk_items_label_code', 'items', type_='foreignkey')

    # Drop the global unique index on short_code.
    if _index_exists('ix_label_pool_short_code'):
        op.drop_index('ix_label_pool_short_code', table_name=_TABLE)

    # Enforce uniqueness per (organization_id, short_code).
    if not _constraint_exists('uq_label_pool_org_short_code'):
        op.create_unique_constraint(
            'uq_label_pool_org_short_code',
            _TABLE,
            ['organization_id', 'short_code'],
        )


def downgrade() -> None:
    if _constraint_exists('uq_label_pool_org_short_code'):
        op.drop_constraint(
            'uq_label_pool_org_short_code',
            _TABLE,
            type_='unique',
        )

    # Restore the global unique index. This fails if duplicate short_codes
    # exist across orgs (the per-org state we came from) — dedupe first.
    if not _index_exists('ix_label_pool_short_code'):
        op.create_index(
            'ix_label_pool_short_code',
            _TABLE,
            ['short_code'],
            unique=True,
        )

    # Restore the legacy FK (idempotent).
    if not _constraint_exists('fk_items_label_code', table='items'):
        op.create_foreign_key(
            'fk_items_label_code', 'items', _TABLE, ['label_code'], ['short_code']
        )
