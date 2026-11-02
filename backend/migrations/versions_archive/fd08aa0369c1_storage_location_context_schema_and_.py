"""storage_location_context_schema_and_item_production_date

Revision ID: fd08aa0369c1
Revises: 0c1958bdf3d7
Create Date: 2026-02-28 13:04:05.732762

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fd08aa0369c1'
down_revision: Union[str, None] = '0c1958bdf3d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add context_schema and behavior_mode to storage_locations
    op.add_column('storage_locations', sa.Column('context_schema', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('storage_locations', sa.Column('behavior_mode', sa.String(50), nullable=False, server_default='STOCK'))

    # Backfill from linked storage_type where present
    op.execute("""
        UPDATE storage_locations sl
        SET
            context_schema = COALESCE(st.context_schema, '[]'::json),
            behavior_mode  = COALESCE(st.behavior_mode, 'STOCK')
        FROM storage_types st
        WHERE sl.storage_type_id = st.id
    """)

    # Add production_date to items
    op.add_column('items', sa.Column('production_date', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('storage_locations', 'context_schema')
    op.drop_column('storage_locations', 'behavior_mode')
    op.drop_column('items', 'production_date')
