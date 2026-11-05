"""warehouse module baseline — create 9 document-related tables.

Initial migration for the warehouse module, extracted from core baseline_001
as part of the module migration isolation effort.

Tables (creation order respects FK dependencies):
- inventory_periods
- tax_rates
- document_profiles (FK → document_templates core table)
- document_type_configs
- documents (self-ref: corrects_document_id, backorder_id)
- document_lines (FK → documents)
- document_relations (FK → documents x2)
- wms_pick_sessions (FK → documents)
- wms_pick_lines (FK → wms_pick_sessions, document_lines)

Two core incremental migrations were guarded for fresh installs:
- ``30cec1e60faf`` (drop cross-module FKs): _constraint_exists now checks
  table existence via to_regclass first.
- ``001_add_stock_reservations`` (a1b2c3d4e5f6): FK to document_lines is
  only added if the table exists.

Revision ID: 001_initial
Revises: None
Create Date: 2026-06-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.migration_helpers import (
    create_index_if_absent,
    create_table_if_absent,
    relation_exists,
)
from sqlalchemy.dialects import postgresql

revision: str = '001_initial'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ('documents',)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- inventory_periods ---
    create_table_if_absent(
        'inventory_periods',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'closed_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('reopened_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'reopened_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('notes', sa.Text(), nullable=True),
    )

    # --- tax_rates ---
    create_table_if_absent(
        'tax_rates',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('rate', sa.Numeric(5, 2), nullable=False),
        sa.Column('code', sa.String(10), nullable=True),
        sa.Column('country', sa.String(2), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )
    create_index_if_absent('ix_tax_rates_organization_id', 'tax_rates', ['organization_id'])

    # --- document_profiles ---
    create_table_if_absent(
        'document_profiles',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('value_tracking_enabled', sa.Boolean(), nullable=False),
        sa.Column('tax_handling', sa.String(20), nullable=False),
        sa.Column('default_tax_rate', sa.Numeric(5, 2), nullable=True),
        sa.Column('require_partner_tax_id', sa.Boolean(), nullable=False),
        sa.Column('numbering_format', sa.String(100), nullable=False),
        sa.Column('type_labels', postgresql.JSON(), nullable=True),
        sa.Column('default_unit', sa.String(20), nullable=False),
        sa.Column('visible_line_fields', postgresql.JSON(), nullable=True),
        sa.Column('print_template', sa.String(50), nullable=False),
        sa.Column('default_currency', sa.String(3), nullable=True),
        sa.Column(
            'default_template_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('document_templates.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('approval_threshold', sa.Numeric(14, 2), nullable=True),
        sa.Column('approval_required_for_types', postgresql.JSON(), nullable=True),
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
        sa.UniqueConstraint('organization_id', name='uq_document_profile_org'),
    )
    create_index_if_absent(
        'ix_document_profiles_organization_id',
        'document_profiles',
        ['organization_id'],
    )

    # --- document_type_configs ---
    create_table_if_absent(
        'document_type_configs',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('document_type', sa.String(15), nullable=False),
        sa.Column(
            'default_source_location_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id'),
            nullable=True,
        ),
        sa.Column(
            'default_target_location_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id'),
            nullable=True,
        ),
        sa.Column('sequence_format', sa.String(50), nullable=False),
        sa.Column('require_partner', sa.Boolean(), nullable=False),
        sa.Column('allowed_fields', postgresql.JSONB()),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.UniqueConstraint(
            'organization_id', 'document_type', name='uq_doctype_config_org_type'
        ),
    )
    create_index_if_absent(
        'ix_document_type_configs_organization_id',
        'document_type_configs',
        ['organization_id'],
    )

    # --- documents (self-referencing FKs) ---
    create_table_if_absent(
        'documents',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('type', sa.String(15), nullable=False),
        sa.Column('number', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column(
            'partner_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('partners.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'source_location_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'target_location_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('scheduled_date', sa.Date(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('external_reference', sa.String(100), nullable=True),
        sa.Column('partner_snapshot', postgresql.JSONB(), nullable=True),
        sa.Column(
            'corrects_document_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('documents.id', ondelete='RESTRICT'),
            nullable=True,
        ),
        sa.Column(
            'backorder_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('documents.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('total_net', sa.Numeric(14, 2), nullable=True),
        sa.Column('total_tax', sa.Numeric(14, 2), nullable=True),
        sa.Column('total_gross', sa.Numeric(14, 2), nullable=True),
        sa.Column('currency', sa.String(3), nullable=True),
        sa.Column(
            'created_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=False,
        ),
        sa.Column(
            'confirmed_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'completed_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
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
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('organization_id', 'number', name='uq_document_org_number'),
    )
    create_index_if_absent('ix_documents_organization_id', 'documents', ['organization_id'])
    create_index_if_absent(
        'ix_documents_corrects_document_id', 'documents', ['corrects_document_id']
    )
    create_index_if_absent('ix_documents_backorder_id', 'documents', ['backorder_id'])
    create_index_if_absent(
        'ix_document_org_type_status',
        'documents',
        ['organization_id', 'type', 'status'],
    )
    create_index_if_absent(
        'ix_document_org_partner', 'documents', ['organization_id', 'partner_id']
    )

    # --- document_lines (FK → documents) ---
    create_table_if_absent(
        'document_lines',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'document_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('documents.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'item_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('items.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'product_template_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('product_templates.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('brand', sa.String(255), nullable=True),
        sa.Column('barcode', sa.String(50), nullable=True),
        sa.Column('quantity', sa.Numeric(12, 3), nullable=False),
        sa.Column('expected_quantity', sa.Numeric(12, 3), nullable=False),
        sa.Column('done_quantity', sa.Numeric(12, 3), nullable=False),
        sa.Column(
            'uom_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('uoms.id'),
            nullable=True,
        ),
        sa.Column('batch_number', sa.String(100), nullable=True),
        sa.Column('serial_number', sa.String(100), nullable=True),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('discrepancy_code', sa.String(50), nullable=True),
        sa.Column('discrepancy_reason', sa.Text(), nullable=True),
        sa.Column('unit_price', sa.Numeric(12, 2), nullable=True),
        sa.Column('tax_rate', sa.Numeric(5, 2), nullable=True),
        sa.Column('line_value', sa.Numeric(14, 2), nullable=True),
        sa.Column('line_tax', sa.Numeric(14, 2), nullable=True),
        sa.Column('line_gross', sa.Numeric(14, 2), nullable=True),
        sa.Column('currency', sa.String(3), nullable=True),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('source_po_line_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('product_snapshot', postgresql.JSONB(), nullable=True),
    )
    create_index_if_absent('ix_document_lines_document_id', 'document_lines', ['document_id'])
    create_index_if_absent(
        'ix_document_lines_source_po_line_id',
        'document_lines',
        ['source_po_line_id'],
    )

    # --- document_relations (FK → documents x2) ---
    create_table_if_absent(
        'document_relations',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'source_document_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('documents.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'target_document_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('documents.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('relation_type', sa.String(30), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )
    create_index_if_absent(
        'ix_doc_relation_source',
        'document_relations',
        ['source_document_id'],
    )
    create_index_if_absent(
        'ix_doc_relation_target',
        'document_relations',
        ['target_document_id'],
    )

    # --- wms_pick_sessions (FK → documents) ---
    create_table_if_absent(
        'wms_pick_sessions',
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
            'document_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('documents.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'assigned_to',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id'),
            nullable=True,
        ),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column(
            'started_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('meta_data', postgresql.JSONB(), nullable=True),
    )
    create_index_if_absent(
        'ix_wms_pick_sessions_organization_id',
        'wms_pick_sessions',
        ['organization_id'],
    )
    create_index_if_absent(
        'ix_wms_pick_sessions_document_id', 'wms_pick_sessions', ['document_id']
    )

    # --- wms_pick_lines (FK → wms_pick_sessions, document_lines) ---
    create_table_if_absent(
        'wms_pick_lines',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'session_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('wms_pick_sessions.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'document_line_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('document_lines.id', ondelete='CASCADE'),
            nullable=False,
        ),
        # A core built after the quant table went (``quantdrop01``) has no
        # table to point at: the column is created bare there, and
        # ``doc_pick_quant_gone01`` drops it in either case.
        sa.Column(
            'quant_id',
            postgresql.UUID(as_uuid=True),
            *(
                [sa.ForeignKey('stock_quants.id', ondelete='SET NULL')]
                if relation_exists('stock_quants')
                else []
            ),
            nullable=True,
        ),
        sa.Column('pick_order', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('picked_quantity', sa.Numeric(12, 3), nullable=False),
        sa.Column('bin_location', sa.String(255), nullable=True),
        sa.Column('product_name', sa.String(255), nullable=True),
        sa.Column('lot_name', sa.String(100), nullable=True),
        sa.Column('expected_quantity', sa.Numeric(12, 3), nullable=False),
        sa.Column('uom_symbol', sa.String(10), nullable=True),
    )
    create_index_if_absent('ix_wms_pick_lines_session_id', 'wms_pick_lines', ['session_id'])
    create_index_if_absent(
        'ix_wms_pick_lines_document_line_id',
        'wms_pick_lines',
        ['document_line_id'],
    )


def downgrade() -> None:
    # Drop children first
    op.drop_index('ix_wms_pick_lines_document_line_id', table_name='wms_pick_lines')
    op.drop_index('ix_wms_pick_lines_session_id', table_name='wms_pick_lines')
    op.drop_table('wms_pick_lines')

    op.drop_index('ix_wms_pick_sessions_document_id', table_name='wms_pick_sessions')
    op.drop_index(
        'ix_wms_pick_sessions_organization_id', table_name='wms_pick_sessions'
    )
    op.drop_table('wms_pick_sessions')

    op.drop_index('ix_doc_relation_target', table_name='document_relations')
    op.drop_index('ix_doc_relation_source', table_name='document_relations')
    op.drop_table('document_relations')

    op.drop_index('ix_document_lines_source_po_line_id', table_name='document_lines')
    op.drop_index('ix_document_lines_document_id', table_name='document_lines')
    op.drop_table('document_lines')

    op.drop_index('ix_document_org_partner', table_name='documents')
    op.drop_index('ix_document_org_type_status', table_name='documents')
    op.drop_index('ix_documents_backorder_id', table_name='documents')
    op.drop_index('ix_documents_corrects_document_id', table_name='documents')
    op.drop_index('ix_documents_organization_id', table_name='documents')
    op.drop_table('documents')

    op.drop_index(
        'ix_document_type_configs_organization_id',
        table_name='document_type_configs',
    )
    op.drop_table('document_type_configs')

    op.drop_index(
        'ix_document_profiles_organization_id', table_name='document_profiles'
    )
    op.drop_table('document_profiles')

    op.drop_index('ix_tax_rates_organization_id', table_name='tax_rates')
    op.drop_table('tax_rates')

    op.drop_table('inventory_periods')
