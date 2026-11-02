"""add org tax_id country and tax_rates table

Revision ID: a95122e492a6
Revises: 3fdf05c3e6d7
Create Date: 2026-05-09 22:45:22.757026

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a95122e492a6'
down_revision: Union[str, None] = '3fdf05c3e6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('organizations', sa.Column('tax_id', sa.String(length=50), nullable=True))
    op.add_column('organizations', sa.Column('country', sa.String(length=2), nullable=True))
    op.create_table(
        'tax_rates',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('rate', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('code', sa.String(length=10), nullable=True),
        sa.Column('country', sa.String(length=2), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_tax_rates_organization_id'), 'tax_rates', ['organization_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_tax_rates_organization_id'), table_name='tax_rates')
    op.drop_table('tax_rates')
    op.drop_column('organizations', 'country')
    op.drop_column('organizations', 'tax_id')
