"""increase_storage_short_code_length

Revision ID: ad16661b8959
Revises: b3ac35f4da34
Create Date: 2026-03-14 23:17:49.942106

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ad16661b8959'
down_revision: Union[str, None] = 'b3ac35f4da34'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'storage_locations',
        'short_code',
        existing_type=sa.String(20),
        type_=sa.String(100),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        'storage_locations',
        'short_code',
        existing_type=sa.String(100),
        type_=sa.String(20),
        existing_nullable=True,
    )
