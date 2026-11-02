"""add name brand barcode to document lines

Revision ID: f3a1b2c4d5e6
Revises: 5d096a9483ea
Create Date: 2026-03-31 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f3a1b2c4d5e6'
down_revision: Union[str, None] = '5d096a9483ea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('document_lines', sa.Column('name', sa.String(255), nullable=True))
    op.add_column('document_lines', sa.Column('brand', sa.String(255), nullable=True))
    op.add_column('document_lines', sa.Column('barcode', sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column('document_lines', 'barcode')
    op.drop_column('document_lines', 'brand')
    op.drop_column('document_lines', 'name')
