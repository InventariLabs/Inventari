"""change documents_target_location_id_fkey to SET NULL

Revision ID: 71d720597a68
Revises: b7f230091ab2
Create Date: 2026-05-30 14:30:29.540079

"""
from typing import Sequence, Union

from alembic import op

revision: str = '71d720597a68'
down_revision: Union[str, None] = 'b7f230091ab2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('documents_target_location_id_fkey', 'documents', type_='foreignkey')
    op.create_foreign_key(None, 'documents', 'storage_locations', ['target_location_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint(None, 'documents', type_='foreignkey')
    op.create_foreign_key('documents_target_location_id_fkey', 'documents', 'storage_locations', ['target_location_id'], ['id'], ondelete='RESTRICT')
