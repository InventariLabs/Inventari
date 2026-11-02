"""Storage short_code unique per organization instead of globally.

Revision ID: storagecode01
Revises: storagelevel02
Create Date: 2026-08-15

``storage_locations.short_code`` carried a global unique index, while the
equivalent column on ``label_pool`` went per-organization back in orglabel01.
The asymmetry was exploitable: short codes are client-supplied on both create
and update, so one tenant could take (or deliberately squat on) a code and
every other tenant was refused it — with an error naming "another location",
which confirmed the row existed in a foreign organization.

Relaxing global uniqueness to (organization_id, short_code) cannot conflict
with existing data: rows unique across the whole table are also unique within
each organization, so no backfill or dedupe is needed.

The standalone index goes with it. Lookups are org-scoped after this change,
and the composite constraint's index leads with organization_id, which serves
them; keeping ix_storage_locations_short_code would only cost writes.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'storagecode01'
down_revision: str | None = 'storagelevel02'
branch_labels: str | None = None
depends_on: str | None = None

_TABLE = 'storage_locations'
_INDEX = 'ix_storage_locations_short_code'
_CONSTRAINT = 'uq_storage_locations_org_short_code'


def _index_exists(index_name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text('SELECT to_regclass(:t)'),
            {'t': f'public.{index_name}'},
        ).scalar()
    )


def _constraint_exists(constraint_name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            'SELECT 1 FROM pg_constraint '
            'WHERE conname = :c AND conrelid = to_regclass(:t)'
        ),
        {'c': constraint_name, 't': f'public.{_TABLE}'},
    ).first()
    return row is not None


def upgrade() -> None:
    if not _constraint_exists(_CONSTRAINT):
        op.create_unique_constraint(
            _CONSTRAINT,
            _TABLE,
            ['organization_id', 'short_code'],
        )

    if _index_exists(_INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)


def downgrade() -> None:
    # Fails when two organizations share a code — the state this migration
    # makes legal. Dedupe before going back.
    if not _index_exists(_INDEX):
        op.create_index(_INDEX, _TABLE, ['short_code'], unique=True)

    if _constraint_exists(_CONSTRAINT):
        op.drop_constraint(_CONSTRAINT, _TABLE, type_='unique')
