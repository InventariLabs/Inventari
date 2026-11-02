"""add pricing fields to document lines and documents

Revision ID: 95ebb9252a8d
Revises: e32b1e5a7d19
Create Date: 2026-04-10 20:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '95ebb9252a8d'
down_revision: Union[str, None] = 'e32b1e5a7d19'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'document_lines',
        sa.Column('unit_price', sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        'document_lines',
        sa.Column('tax_rate', sa.Numeric(5, 2), nullable=True),
    )
    op.add_column(
        'document_lines',
        sa.Column('line_value', sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        'document_lines',
        sa.Column('line_tax', sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        'document_lines',
        sa.Column('line_gross', sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        'document_lines',
        sa.Column('currency', sa.String(3), nullable=True),
    )
    op.add_column(
        'documents',
        sa.Column('total_net', sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        'documents',
        sa.Column('total_tax', sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        'documents',
        sa.Column('total_gross', sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        'documents',
        sa.Column('currency', sa.String(3), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('documents', 'currency')
    op.drop_column('documents', 'total_gross')
    op.drop_column('documents', 'total_tax')
    op.drop_column('documents', 'total_net')
    op.drop_column('document_lines', 'currency')
    op.drop_column('document_lines', 'line_gross')
    op.drop_column('document_lines', 'line_tax')
    op.drop_column('document_lines', 'line_value')
    op.drop_column('document_lines', 'tax_rate')
    op.drop_column('document_lines', 'unit_price')
