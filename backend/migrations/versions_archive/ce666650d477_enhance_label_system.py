"""enhance_label_system

Revision ID: ce666650d477
Revises: 13bf636715bf
Create Date: 2026-01-30 20:12:11.435299

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ce666650d477'
down_revision: Union[str, None] = '13bf636715bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('label_pool', sa.Column('label_type', sa.String(50), server_default='GENERIC', nullable=False))
    op.add_column('label_pool', sa.Column('description', sa.String(255), nullable=True))
    op.add_column('label_pool', sa.Column('target_storage_location_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('fk_label_pool_target_storage', 'label_pool', 'storage_locations', ['target_storage_location_id'], ['id'], ondelete='SET NULL')

def downgrade() -> None:
    op.drop_constraint('fk_label_pool_target_storage', 'label_pool', type_='foreignkey')
    op.drop_column('label_pool', 'target_storage_location_id')
    op.drop_column('label_pool', 'description')
    op.drop_column('label_pool', 'label_type')
