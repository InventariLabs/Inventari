"""add discrepancy reason to document lines

Revision ID: d1f8f0f7a2b4
Revises: b47e41c0ad9a
Create Date: 2026-04-09 22:12:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1f8f0f7a2b4'
down_revision: Union[str, None] = 'b47e41c0ad9a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('document_lines', sa.Column('discrepancy_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('document_lines', 'discrepancy_reason')