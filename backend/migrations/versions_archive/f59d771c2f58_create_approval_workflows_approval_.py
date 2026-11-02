"""create approval_workflows, approval_requests, approval_decisions tables

Revision ID: f59d771c2f58
Revises: 5aed48d87212
Create Date: 2026-04-30 21:27:58.043589

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f59d771c2f58'
down_revision: Union[str, None] = '5aed48d87212'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'approval_workflows',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('target_type', sa.String(50), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('stages', sa.JSON(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'target_type', name='uq_workflow_org_target'),
    )
    op.create_index(op.f('ix_approval_workflows_organization_id'), 'approval_workflows', ['organization_id'], unique=False)

    op.create_table(
        'approval_requests',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('workflow_id', sa.UUID(), nullable=False),
        sa.Column('target_type', sa.String(50), nullable=False),
        sa.Column('target_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column('current_stage', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('total_stages', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=False),
        sa.Column('meta_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workflow_id'], ['approval_workflows.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_approval_requests_organization_id'), 'approval_requests', ['organization_id'], unique=False)
    op.create_index('ix_approval_requests_target', 'approval_requests', ['target_type', 'target_id', 'organization_id'], unique=False)

    op.create_table(
        'approval_decisions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('approval_request_id', sa.UUID(), nullable=False),
        sa.Column('stage_order', sa.Integer(), nullable=False),
        sa.Column('approver_id', sa.UUID(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['approval_request_id'], ['approval_requests.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['approver_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_approval_decisions_approval_request_id'), 'approval_decisions', ['approval_request_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_approval_decisions_approval_request_id'), table_name='approval_decisions')
    op.drop_table('approval_decisions')
    op.drop_index('ix_approval_requests_target', table_name='approval_requests')
    op.drop_index(op.f('ix_approval_requests_organization_id'), table_name='approval_requests')
    op.drop_table('approval_requests')
    op.drop_index(op.f('ix_approval_workflows_organization_id'), table_name='approval_workflows')
    op.drop_table('approval_workflows')
