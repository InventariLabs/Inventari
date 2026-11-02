"""approvals module baseline — create approval_workflows, approval_requests, approval_decisions.

Initial migration for the approvals module, extracted from core baseline_001
as part of the module migration isolation effort.

These tables were previously created by the consolidated
``baseline_001_full_schema.py`` with cancelled_by/cancelled_at added by
core migration ``c0a1b2c3d4e5``. They now belong to the approvals module
so ``module enable approvals`` / ``module disable approvals`` can manage
them independently via ``alembic_version_approvals``.

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
branch_labels: str | Sequence[str] | None = ('approvals',)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_table_if_absent(
        'approval_workflows',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('target_type', sa.String(50), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('stages', postgresql.JSON(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            'organization_id', 'target_type', name='uq_workflow_org_target'
        ),
    )
    create_index_if_absent(
        'ix_approval_workflows_organization_id',
        'approval_workflows',
        ['organization_id'],
    )

    create_table_if_absent(
        'approval_requests',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'workflow_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('approval_workflows.id', ondelete='RESTRICT'),
            nullable=False,
        ),
        sa.Column('target_type', sa.String(50), nullable=False),
        sa.Column('target_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='PENDING'),
        sa.Column('current_stage', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('total_stages', sa.Integer(), nullable=False),
        sa.Column(
            'created_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'cancelled_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('meta_data', postgresql.JSONB(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )
    create_index_if_absent(
        'ix_approval_requests_organization_id',
        'approval_requests',
        ['organization_id'],
    )
    create_index_if_absent(
        'ix_approval_requests_target',
        'approval_requests',
        ['target_type', 'target_id', 'organization_id'],
    )
    create_index_if_absent(
        'uq_pending_request',
        'approval_requests',
        ['organization_id', 'target_type', 'target_id'],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'IN_PROGRESS')"),
    )

    create_table_if_absent(
        'approval_decisions',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'approval_request_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('approval_requests.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('stage_order', sa.Integer(), nullable=False),
        sa.Column(
            'approver_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('status', sa.String(20), nullable=False, server_default='PENDING'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )
    create_index_if_absent(
        'ix_approval_decisions_approval_request_id',
        'approval_decisions',
        ['approval_request_id'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_approval_decisions_approval_request_id', table_name='approval_decisions'
    )
    op.drop_table('approval_decisions')

    op.drop_index('uq_pending_request', table_name='approval_requests')
    op.drop_index('ix_approval_requests_target', table_name='approval_requests')
    op.drop_index(
        'ix_approval_requests_organization_id', table_name='approval_requests'
    )
    op.drop_table('approval_requests')

    op.drop_index(
        'ix_approval_workflows_organization_id', table_name='approval_workflows'
    )
    op.drop_table('approval_workflows')
