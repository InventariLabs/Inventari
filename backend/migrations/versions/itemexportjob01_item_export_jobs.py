"""item export jobs - an export that outgrew one request, followed by its screen

Revision ID: itemexportjob01
Revises: spoons01
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'itemexportjob01'
down_revision: str | None = 'spoons01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'item_export_jobs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('total', sa.Integer(), nullable=False),
        sa.Column('processed', sa.Integer(), nullable=False),
        sa.Column('file_path', sa.String(length=512), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_item_export_jobs_organization_id'),
        'item_export_jobs',
        ['organization_id'],
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_item_export_jobs_organization_id'), table_name='item_export_jobs'
    )
    op.drop_table('item_export_jobs')
