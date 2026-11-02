"""add po_settings table (PO approval config)

Revision ID: po_settings01
Revises: po_pricelist01
Create Date: 2026-08-02

Per-org purchase order settings. ``approval_threshold`` (net total
above which a PO must be approved) and ``approval_required`` (all POs
require approval) feed the confirm flow in
``app/modules/purchase_orders/_service_workflow.py``.

Analogy to ``DocumentProfile`` in the documents module — one row per
organization, created lazily on first settings access.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'po_settings01'
down_revision: str | None = 'po_pricelist01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'po_settings',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('approval_threshold', sa.Numeric(14, 2), nullable=True),
        sa.Column(
            'approval_required',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
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
        sa.UniqueConstraint('organization_id', name='uq_po_settings_org'),
    )
    op.create_index(
        'ix_po_settings_organization_id',
        'po_settings',
        ['organization_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_po_settings_organization_id', table_name='po_settings')
    op.drop_table('po_settings')
