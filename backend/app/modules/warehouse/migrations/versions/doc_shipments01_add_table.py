"""add document_shipments and the profile's tracking link templates.

Revision ID: doc_shipments01
Revises: doc_pick_multi01
Create Date: 2026-10-17

Completing a dispatch can record its hand-over to a carrier: the carrier as
the operator names it, the tracking number, when and by whom. One shipment
per document, written in the completion's transaction.
``document_profiles.tracking_url_templates`` holds the organization's own
tracking link templates, by carrier name, beside the built-in ones.

Downgrade drops the table and the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_shipments01'
down_revision: str | None = 'doc_pick_multi01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'document_shipments',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column(
            'organization_id',
            sa.UUID(),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'document_id',
            sa.UUID(),
            sa.ForeignKey('documents.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('carrier', sa.String(100), nullable=False),
        sa.Column('tracking_number', sa.String(100), nullable=True),
        sa.Column('shipped_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            'shipped_by',
            sa.UUID(),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint('document_id', name='uq_document_shipments_document'),
    )
    op.create_index(
        'ix_document_shipments_organization_id',
        'document_shipments',
        ['organization_id'],
    )
    op.add_column(
        'document_profiles',
        sa.Column('tracking_url_templates', sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('document_profiles', 'tracking_url_templates')
    op.drop_index('ix_document_shipments_organization_id', 'document_shipments')
    op.drop_table('document_shipments')
