"""equipment module baseline — create equipment tables + audit campaign tables.

Initial migration for the equipment module, extracted from core baseline_001
as part of the module migration isolation effort.

These six tables were previously created by the consolidated
``baseline_001_full_schema.py``. They now belong to the equipment module so
``module enable equipment`` / ``module disable equipment`` can manage them
independently via ``alembic_version_equipment``.

Tables (creation order respects FK dependencies):
- audit_campaigns (parent of audit_responses)
- equipment_document_templates
- equipment_attachments
- equipment_maintenance_logs
- equipment_assignments (parent of audit_responses)
- audit_responses (FK → audit_campaigns, equipment_assignments)

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
branch_labels: str | Sequence[str] | None = ('equipment',)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- audit_campaigns (parent, no module-internal FK) ---
    create_table_if_absent(
        'audit_campaigns',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('scope_type', sa.String(20), nullable=False),
        sa.Column('scope_filter_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('launched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deadline', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reminder_days_before', sa.Integer(), nullable=False),
        sa.Column('last_reminder_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('email_subject', sa.String(255), nullable=True),
        sa.Column('email_body', sa.Text(), nullable=True),
        sa.Column(
            'created_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=False,
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
        'ix_audit_campaigns_organization_id', 'audit_campaigns', ['organization_id']
    )
    create_index_if_absent('ix_audit_campaigns_org', 'audit_campaigns', ['organization_id'])

    # --- equipment_document_templates ---
    create_table_if_absent(
        'equipment_document_templates',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('document_type', sa.String(30), nullable=False),
        sa.Column('body_html', sa.Text(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column(
            'created_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=False,
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
        'ix_equipment_document_templates_organization_id',
        'equipment_document_templates',
        ['organization_id'],
    )
    create_index_if_absent(
        'ix_eq_doc_tpl_org', 'equipment_document_templates', ['organization_id']
    )

    # --- equipment_attachments ---
    create_table_if_absent(
        'equipment_attachments',
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
            'item_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('items.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('file_path', sa.String(500), nullable=False),
        sa.Column('original_name', sa.String(255), nullable=False),
        sa.Column('file_type', sa.String(30), nullable=False),
        sa.Column('content_type', sa.String(100), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column(
            'uploaded_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )
    create_index_if_absent(
        'ix_equipment_attachments_organization_id',
        'equipment_attachments',
        ['organization_id'],
    )
    create_index_if_absent(
        'ix_equipment_attachments_item_id', 'equipment_attachments', ['item_id']
    )
    create_index_if_absent(
        'ix_eq_attachments_org_item',
        'equipment_attachments',
        ['organization_id', 'item_id'],
    )

    # --- equipment_maintenance_logs ---
    create_table_if_absent(
        'equipment_maintenance_logs',
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
            'item_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('items.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('maintenance_type', sa.String(30), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('cost', sa.Numeric(10, 2), nullable=True),
        sa.Column('currency', sa.String(3), nullable=True),
        sa.Column('performed_at', sa.Date(), nullable=False),
        sa.Column('performed_by', sa.String(255), nullable=True),
        sa.Column(
            'service_partner_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('partners.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('next_maintenance_at', sa.Date(), nullable=True),
        sa.Column(
            'created_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=False,
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
        'ix_equipment_maintenance_logs_organization_id',
        'equipment_maintenance_logs',
        ['organization_id'],
    )
    create_index_if_absent(
        'ix_equipment_maintenance_logs_item_id',
        'equipment_maintenance_logs',
        ['item_id'],
    )
    create_index_if_absent(
        'ix_eq_maintenance_org_item',
        'equipment_maintenance_logs',
        ['organization_id', 'item_id'],
    )

    # --- equipment_assignments ---
    create_table_if_absent(
        'equipment_assignments',
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
            'item_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('items.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'assignee_partner_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('partners.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'checkout_location_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('assigned_to_name', sa.String(255), nullable=False),
        sa.Column('assigned_to_email', sa.String(255), nullable=True),
        sa.Column('checked_out_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expected_return_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('checked_in_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'checked_out_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=False,
        ),
        sa.Column(
            'checked_in_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('checkout_notes', sa.Text(), nullable=True),
        sa.Column('checkin_notes', sa.Text(), nullable=True),
        sa.Column('checkin_condition', sa.String(30), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )
    create_index_if_absent(
        'ix_equipment_assignments_organization_id',
        'equipment_assignments',
        ['organization_id'],
    )
    create_index_if_absent(
        'ix_equipment_assignments_item_id', 'equipment_assignments', ['item_id']
    )
    create_index_if_absent(
        'ix_equipment_assignments_assignee_partner_id',
        'equipment_assignments',
        ['assignee_partner_id'],
    )
    create_index_if_absent(
        'ix_equipment_assignments_checkout_location_id',
        'equipment_assignments',
        ['checkout_location_id'],
    )
    create_index_if_absent(
        'ix_eq_assignments_org_item',
        'equipment_assignments',
        ['organization_id', 'item_id'],
    )
    create_index_if_absent(
        'uq_eq_assignments_active_per_item',
        'equipment_assignments',
        ['item_id'],
        unique=True,
        postgresql_where=sa.text('checked_in_at IS NULL'),
    )

    # --- audit_responses (child: FK → audit_campaigns, equipment_assignments) ---
    create_table_if_absent(
        'audit_responses',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'campaign_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('audit_campaigns.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'assignment_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('equipment_assignments.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('assignee_email', sa.String(255), nullable=False),
        sa.Column('assignee_name', sa.String(255), nullable=False),
        sa.Column('token', sa.String(86), nullable=False),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('dispute_reason', sa.Text(), nullable=True),
        sa.Column('dispute_type', sa.String(30), nullable=True),
        sa.Column('response_ip', sa.String(45), nullable=True),
        sa.Column('response_user_agent', sa.String(500), nullable=True),
        sa.Column('email_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reminder_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )
    create_index_if_absent(
        'ix_audit_responses_organization_id',
        'audit_responses',
        ['organization_id'],
    )
    create_index_if_absent(
        'ix_audit_responses_assignment_id', 'audit_responses', ['assignment_id']
    )
    create_index_if_absent(
        'ix_audit_responses_campaign_id', 'audit_responses', ['campaign_id']
    )
    create_index_if_absent(
        'ix_audit_responses_token', 'audit_responses', ['token'], unique=True
    )
    create_index_if_absent(
        'ix_audit_responses_campaign_status',
        'audit_responses',
        ['campaign_id', 'status'],
    )


def downgrade() -> None:
    # Drop children first (audit_responses depends on audit_campaigns + equipment_assignments)
    op.drop_index('ix_audit_responses_campaign_status', table_name='audit_responses')
    op.drop_index('ix_audit_responses_token', table_name='audit_responses')
    op.drop_index('ix_audit_responses_campaign_id', table_name='audit_responses')
    op.drop_index('ix_audit_responses_assignment_id', table_name='audit_responses')
    op.drop_index('ix_audit_responses_organization_id', table_name='audit_responses')
    op.drop_table('audit_responses')

    op.drop_index(
        'uq_eq_assignments_active_per_item', table_name='equipment_assignments'
    )
    op.drop_index('ix_eq_assignments_org_item', table_name='equipment_assignments')
    op.drop_index(
        'ix_equipment_assignments_checkout_location_id',
        table_name='equipment_assignments',
    )
    op.drop_index(
        'ix_equipment_assignments_assignee_partner_id',
        table_name='equipment_assignments',
    )
    op.drop_index(
        'ix_equipment_assignments_item_id', table_name='equipment_assignments'
    )
    op.drop_index(
        'ix_equipment_assignments_organization_id',
        table_name='equipment_assignments',
    )
    op.drop_table('equipment_assignments')

    op.drop_index('ix_eq_maintenance_org_item', table_name='equipment_maintenance_logs')
    op.drop_index(
        'ix_equipment_maintenance_logs_item_id',
        table_name='equipment_maintenance_logs',
    )
    op.drop_index(
        'ix_equipment_maintenance_logs_organization_id',
        table_name='equipment_maintenance_logs',
    )
    op.drop_table('equipment_maintenance_logs')

    op.drop_index('ix_eq_attachments_org_item', table_name='equipment_attachments')
    op.drop_index(
        'ix_equipment_attachments_item_id', table_name='equipment_attachments'
    )
    op.drop_index(
        'ix_equipment_attachments_organization_id',
        table_name='equipment_attachments',
    )
    op.drop_table('equipment_attachments')

    op.drop_index('ix_eq_doc_tpl_org', table_name='equipment_document_templates')
    op.drop_index(
        'ix_equipment_document_templates_organization_id',
        table_name='equipment_document_templates',
    )
    op.drop_table('equipment_document_templates')

    op.drop_index('ix_audit_campaigns_org', table_name='audit_campaigns')
    op.drop_index('ix_audit_campaigns_organization_id', table_name='audit_campaigns')
    op.drop_table('audit_campaigns')
