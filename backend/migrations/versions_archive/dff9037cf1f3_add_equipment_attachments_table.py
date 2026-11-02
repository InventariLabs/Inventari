"""add equipment_attachments table

Revision ID: dff9037cf1f3
Revises: a1b2c3d4e5f7
Create Date: 2026-05-18 13:02:24.100038

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'dff9037cf1f3'  # noqa: F841 — read by Alembic runtime
down_revision: Union[str, None] = 'a1b2c3d4e5f7'  # noqa: F841
branch_labels: Union[str, Sequence[str], None] = None  # noqa: F841
depends_on: Union[str, Sequence[str], None] = None  # noqa: F841


def upgrade() -> None:
    op.create_table('equipment_attachments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('item_id', sa.Uuid(), nullable=False),
    sa.Column('file_path', sa.String(length=500), nullable=False),
    sa.Column('original_name', sa.String(length=255), nullable=False),
    sa.Column('file_type', sa.String(length=30), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('uploaded_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['item_id'], ['items.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_eq_attachments_org_item', 'equipment_attachments', ['organization_id', 'item_id'], unique=False)
    op.create_index(op.f('ix_equipment_attachments_item_id'), 'equipment_attachments', ['item_id'], unique=False)
    op.create_index(op.f('ix_equipment_attachments_organization_id'), 'equipment_attachments', ['organization_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_equipment_attachments_organization_id'), table_name='equipment_attachments')
    op.drop_index(op.f('ix_equipment_attachments_item_id'), table_name='equipment_attachments')
    op.drop_index('ix_eq_attachments_org_item', table_name='equipment_attachments')
    op.drop_table('equipment_attachments')
