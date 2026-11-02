"""printing module baseline — the print queue: print_agents and print_jobs.

Revision ID: 001_initial
Revises: None
Create Date: 2026-10-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.migration_helpers import create_table_if_absent

revision: str = '001_initial'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ('printing',)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_table_if_absent(
        'print_agents',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('printer_type', sa.String(50), nullable=False),
        sa.Column('media', sa.String(50), nullable=False),
        sa.Column('width_mm', sa.Numeric(6, 1), nullable=False),
        sa.Column('height_mm', sa.Numeric(6, 1), nullable=False),
        sa.Column(
            'last_seen_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.UniqueConstraint('organization_id', 'name', name='uq_print_agents_org_name'),
    )
    create_table_if_absent(
        'print_jobs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        sa.Column(
            'agent_id',
            UUID(as_uuid=True),
            sa.ForeignKey('print_agents.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        sa.Column('status', sa.String(20), nullable=False, index=True),
        sa.Column('labels', JSONB, nullable=False),
        sa.Column(
            'created_by',
            UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('print_jobs')
    op.drop_table('print_agents')
