"""add_scheduled_date_and_nullable_target_location

Revision ID: f8baab5a52d7
Revises: 1a681f9d2f97
Create Date: 2026-04-08 21:50:45.274813

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8baab5a52d7'
down_revision: Union[str, None] = '1a681f9d2f97'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('scheduled_date', sa.Date(), nullable=True))
    op.alter_column('documents', 'target_location_id',
               existing_type=sa.UUID(),
               nullable=True)


def downgrade() -> None:
    op.alter_column('documents', 'target_location_id',
               existing_type=sa.UUID(),
               nullable=False)
    op.drop_column('documents', 'scheduled_date')
