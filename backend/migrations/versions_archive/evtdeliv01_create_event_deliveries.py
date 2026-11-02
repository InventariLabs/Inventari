"""create event_deliveries table (failed event handlers, retried or dead)

Revision ID: evtdeliv01
Revises: seedfield01
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'evtdeliv01'
down_revision: str | None = 'seedfield01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'event_deliveries',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('event_id', sa.String(64), nullable=False),
        sa.Column('event', sa.String(100), nullable=False),
        sa.Column('handler', sa.String(255), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('payload', postgresql.JSONB(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            'event_id', 'handler', name='uq_event_deliveries_event_handler'
        ),
    )
    op.create_index(
        'ix_event_deliveries_organization_id', 'event_deliveries', ['organization_id']
    )
    op.create_index(
        'ix_event_deliveries_status_next_attempt',
        'event_deliveries',
        ['status', 'next_attempt_at'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_event_deliveries_status_next_attempt', table_name='event_deliveries'
    )
    op.drop_index('ix_event_deliveries_organization_id', table_name='event_deliveries')
    op.drop_table('event_deliveries')
