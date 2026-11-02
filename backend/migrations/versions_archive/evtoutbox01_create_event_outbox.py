"""create event_outbox table (transactional outbox)

Revision ID: evtoutbox01
Revises: coreaudit01
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'evtoutbox01'
down_revision: str | None = 'coreaudit01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'event_outbox',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('event', sa.String(100), nullable=False),
        sa.Column('payload', postgresql.JSONB(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_index('ix_event_outbox_organization_id', 'event_outbox', ['organization_id'])
    # Relay polling index: unpublished rows in creation order.
    op.create_index(
        'ix_event_outbox_unpublished',
        'event_outbox',
        ['created_at'],
        postgresql_where=sa.text('published_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('ix_event_outbox_unpublished', table_name='event_outbox')
    op.drop_index('ix_event_outbox_organization_id', table_name='event_outbox')
    op.drop_table('event_outbox')
