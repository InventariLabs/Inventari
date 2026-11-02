"""add shopping_exclusions table

Revision ID: 229bfe19c98b
Revises: 171b6b81e2ff
Create Date: 2026-05-10 18:17:29.247969

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '229bfe19c98b'
down_revision: Union[str, None] = '171b6b81e2ff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'shopping_exclusions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('name_normalized', sa.String(length=255), nullable=False),
        sa.Column('template_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['template_id'], ['product_templates.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'organization_id', 'name_normalized',
            name='uq_shopping_exclusions_org_name',
        ),
    )
    op.create_index(
        op.f('ix_shopping_exclusions_organization_id'),
        'shopping_exclusions',
        ['organization_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_shopping_exclusions_organization_id'),
        table_name='shopping_exclusions',
    )
    op.drop_table('shopping_exclusions')
