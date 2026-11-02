"""example_widgets module baseline — create example_widgets table.

Initial migration for the example_widgets module. Mirrors the Widget
model in ``app/modules/example_widgets/models.py`` so that fresh
installs create the table via alembic rather than relying on
``Base.metadata.create_all`` at runtime.

Revision ID: 001_initial
Revises: None
Create Date: 2026-06-27

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.module_sdk import create_index_if_absent, create_table_if_absent
from sqlalchemy.dialects.postgresql import UUID

revision: str = '001_initial'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ('example_widgets',)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_table_if_absent(
        'example_widgets',
        sa.Column(
            'id',
            UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            'organization_id',
            UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column(
            'color',
            sa.String(30),
            nullable=False,
            server_default='blue',
        ),
        sa.Column(
            'quantity',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),
        sa.Column(
            'is_active',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('true'),
        ),
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
    )
    create_index_if_absent(
        'ix_example_widgets_organization_id',
        'example_widgets',
        ['organization_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_example_widgets_organization_id', table_name='example_widgets')
    op.drop_table('example_widgets')