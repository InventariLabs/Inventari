"""add module_name to items

Revision ID: itemowner01
Revises: tplsource01
Create Date: 2026-08-25

Which vertical module a record belongs to. The general lists used to answer
that from the record's category alone, so an asset saved without one — the
equipment form never required a category — was indistinguishable from an
ordinary product and stayed on the list the organization had asked to keep
module data out of.
"""

import sqlalchemy as sa
from alembic import op

revision = 'itemowner01'
down_revision = 'tplsource01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'items', sa.Column('module_name', sa.String(length=50), nullable=True)
    )
    op.create_index('ix_items_module_name', 'items', ['module_name'])


def downgrade() -> None:
    op.drop_index('ix_items_module_name', table_name='items')
    op.drop_column('items', 'module_name')
