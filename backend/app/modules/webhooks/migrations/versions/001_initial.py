"""webhooks module baseline — create webhook_endpoints and webhook_delivery_logs.

Initial migration for the webhooks module, extracted from core baseline_001
as part of the module migration isolation effort.

These tables were previously created by the consolidated
``baseline_001_full_schema.py``. They now belong to the webhooks module so
that ``module enable webhooks`` / ``module disable webhooks`` can manage
them independently via the per-module version table
``alembic_version_webhooks``.

Revision ID: 001_initial
Revises: None
Create Date: 2026-06-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.migration_helpers import create_index_if_absent, create_table_if_absent
from sqlalchemy.dialects import postgresql

revision: str = '001_initial'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ('webhooks',)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Parent table — must come before delivery_logs (FK target).
    create_table_if_absent(
        'webhook_endpoints',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('url', sa.String(2048), nullable=False),
        sa.Column('secret', sa.String(512)),
        sa.Column('http_method', sa.String(10), nullable=False, server_default='POST'),
        sa.Column('event_types', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('max_retries', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('retry_backoff_seconds', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('timeout_seconds', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('last_triggered_at', sa.DateTime(timezone=True)),
        sa.Column('last_status_code', sa.Integer()),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False, server_default='0'),
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
        'ix_webhook_endpoints_organization_id',
        'webhook_endpoints',
        ['organization_id'],
    )

    create_table_if_absent(
        'webhook_delivery_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            'webhook_endpoint_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('webhook_endpoints.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('payload_json', postgresql.JSONB(), nullable=False),
        sa.Column('status_code', sa.Integer()),
        sa.Column('response_body', sa.Text()),
        sa.Column('error_message', sa.Text()),
        sa.Column('attempt_number', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('next_retry_at', sa.DateTime(timezone=True)),
        sa.Column('delivery_status', sa.String(20), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )
    create_index_if_absent(
        'ix_webhook_delivery_logs_organization_id',
        'webhook_delivery_logs',
        ['organization_id'],
    )
    create_index_if_absent(
        'ix_webhook_delivery_logs_webhook_endpoint_id',
        'webhook_delivery_logs',
        ['webhook_endpoint_id'],
    )


def downgrade() -> None:
    # Child first, then parent (reverse FK dependency order).
    op.drop_index(
        'ix_webhook_delivery_logs_webhook_endpoint_id', table_name='webhook_delivery_logs'
    )
    op.drop_index(
        'ix_webhook_delivery_logs_organization_id', table_name='webhook_delivery_logs'
    )
    op.drop_table('webhook_delivery_logs')

    op.drop_index('ix_webhook_endpoints_organization_id', table_name='webhook_endpoints')
    op.drop_table('webhook_endpoints')
