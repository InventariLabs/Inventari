"""Switch stock_take_items.item_id FK to ON DELETE SET NULL.

Revision ID: 002_set_null_item_fk
Revises: 001_initial
Create Date: 2026-08-17

Purging an item used to CASCADE-delete its stock-take lines, destroying the
counting evidence. The ``before_purge`` interceptor now blocks that path, but
it only exists while the module is enabled — this constraint change is the
defense-in-depth so the rows survive (``item_name`` is denormalised) even if
the purge happens with the module switched off.

Downgrade restores the CASCADE behaviour.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = '002_set_null_item_fk'
down_revision: str | None = '001_initial'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = 'stock_take_items'
_NEW_CONSTRAINT = 'stock_take_items_item_id_fkey'


def _find_item_fk_constraint(bind: Connection) -> str | None:
    """Name of the current item_id FK — named explicitly here, but the table
    was historically created from the core baseline too, so resolve it from
    the catalog instead of assuming the name."""
    value = bind.execute(
        sa.text(
            'SELECT conname FROM pg_constraint '
            "WHERE conrelid = 'stock_take_items'::regclass "
            "AND contype = 'f' "
            "AND conname LIKE '%item_id%'"
        )
    ).scalar()
    return str(value) if value else None


def upgrade() -> None:
    bind = op.get_bind()
    existing = _find_item_fk_constraint(bind)
    if existing and existing != _NEW_CONSTRAINT:
        bind.execute(sa.text(f'ALTER TABLE {_TABLE} DROP CONSTRAINT {existing}'))
    bind.execute(
        sa.text(f'ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS {_NEW_CONSTRAINT}')
    )
    bind.execute(
        sa.text(
            f'ALTER TABLE {_TABLE} ADD CONSTRAINT {_NEW_CONSTRAINT} '
            'FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE SET NULL'
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    existing = _find_item_fk_constraint(bind)
    if existing and existing != _NEW_CONSTRAINT:
        bind.execute(sa.text(f'ALTER TABLE {_TABLE} DROP CONSTRAINT {existing}'))
    bind.execute(
        sa.text(f'ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS {_NEW_CONSTRAINT}')
    )
    bind.execute(
        sa.text(
            f'ALTER TABLE {_TABLE} ADD CONSTRAINT {_NEW_CONSTRAINT} '
            'FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE'
        )
    )
