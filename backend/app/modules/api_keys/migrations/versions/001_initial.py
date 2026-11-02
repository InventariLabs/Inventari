"""api_keys module baseline — create api_keys table.

This is the initial migration for the api_keys module, created when module
migrations were split from the core chain. It represents the current schema of
the api_keys table (as of 2026-06-10).

Revision ID: 001_initial
Revises: None
Create Date: 2026-06-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.migration_helpers import create_table_if_absent
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = '001_initial'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ('api_keys',)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_table_if_absent(
        'api_keys',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        sa.Column(
            'user_id',
            UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('hashed_key', sa.String(64), nullable=False, unique=True, index=True),
        sa.Column('key_prefix', sa.String(20), nullable=False),
        sa.Column(
            'scopes',
            JSON,
            nullable=False,
            server_default='["read", "write"]',
        ),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table('api_keys')
