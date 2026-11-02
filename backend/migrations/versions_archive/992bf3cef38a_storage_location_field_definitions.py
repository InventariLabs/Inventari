"""storage_location_field_definitions

Revision ID: 992bf3cef38a
Revises: fd08aa0369c1
Create Date: 2026-02-28 14:53:26.521299

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '992bf3cef38a'
down_revision: Union[str, None] = 'fd08aa0369c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOTE: context_schema, behavior_mode and production_date are already added
    # by the previous migration fd08aa0369c1. This migration only adds
    # field_definitions to storage_locations.
    op.add_column('storage_locations', sa.Column('field_definitions', sa.JSON(), server_default='[]', nullable=False))

    # Backfill field_definitions from linked storage_type
    op.execute("""
        UPDATE storage_locations sl
        SET field_definitions = COALESCE(st.field_definitions, '[]'::json)
        FROM storage_types st
        WHERE sl.storage_type_id = st.id
    """)


def downgrade() -> None:
    op.drop_column('storage_locations', 'field_definitions')
