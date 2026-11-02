"""add picked_items JSONB to picking_session_items for multi-item partial picking

Revision ID: pickitems01
Revises: deadprice01
Create Date: 2026-06-18 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = 'pickitems01'
down_revision: Union[str, None] = 'deadprice01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text('SELECT to_regclass(:t)'), {'t': f'public.{table_name}'}
        ).scalar()
    )


def upgrade() -> None:
    # Guard: on fresh installs, picking_session_items is created by the
    # recipes module migration (001_initial) with this column already present.
    if not _table_exists('picking_session_items'):
        return
    op.add_column(
        'picking_session_items',
        sa.Column('picked_items', JSONB(), nullable=True),
    )


def downgrade() -> None:
    if not _table_exists('picking_session_items'):
        return
    op.drop_column('picking_session_items', 'picked_items')
