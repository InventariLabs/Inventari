"""add_parent_id_to_storage_locations

Revision ID: a1b2c3d4e5f6
Revises: 7031d8273a07
Create Date: 2026-02-25 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f0'
down_revision: Union[str, None] = '7031d8273a07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'storage_locations',
        sa.Column('parent_id', sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        'fk_storage_locations_parent_id',
        'storage_locations',
        'storage_locations',
        ['parent_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        'ix_storage_locations_parent_id',
        'storage_locations',
        ['parent_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_storage_locations_parent_id', table_name='storage_locations')
    op.drop_constraint(
        'fk_storage_locations_parent_id',
        'storage_locations',
        type_='foreignkey',
    )
    op.drop_column('storage_locations', 'parent_id')
