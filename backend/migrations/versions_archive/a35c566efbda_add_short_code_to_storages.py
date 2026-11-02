"""add_short_code_to_storages

Revision ID: a35c566efbda
Revises: ce666650d477
Create Date: 2026-01-31 00:10:19.438970

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a35c566efbda'
down_revision: Union[str, None] = 'ce666650d477'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('storage_locations', sa.Column('short_code', sa.String(20), nullable=True))
    op.create_unique_constraint('uq_storage_location_short_code', 'storage_locations', ['short_code'])

def downgrade() -> None:
    op.drop_constraint('uq_storage_location_short_code', 'storage_locations', type_='unique')
    op.drop_column('storage_locations', 'short_code')
