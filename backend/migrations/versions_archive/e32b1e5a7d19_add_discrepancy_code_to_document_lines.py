"""add discrepancy code to document lines

Revision ID: e32b1e5a7d19
Revises: d1f8f0f7a2b4
Create Date: 2026-04-09 22:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e32b1e5a7d19'
down_revision: Union[str, None] = 'd1f8f0f7a2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('document_lines', sa.Column('discrepancy_code', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('document_lines', 'discrepancy_code')