"""add document_extra_costs table (landed costs on a receipt).

Revision ID: doc_extra_costs01
Revises: doc_executed_location01
Create Date: 2026-08-29

Freight, duty and insurance belong in the value of the goods they arrived
with. Without them the shelf is worth what the supplier invoiced and nothing
else, so every margin computed from it is wrong by the cost of getting the
goods there.

The rows live with the receipt and are spread over its lines when it is
posted. They are accepted only while it is unposted: once the layers are
written the goods may already have left, and there is nothing left to charge.

Downgrade drops the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_extra_costs01'
down_revision: str | None = 'doc_register_pagination01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'document_extra_costs',
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
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=True),
        sa.Column(
            'allocation_method',
            sa.String(length=10),
            nullable=False,
            server_default='value',
        ),
        sa.Column('note', sa.String(length=255), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            'created_by',
            sa.UUID(),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.CheckConstraint('amount > 0', name='ck_document_extra_costs_amount'),
    )
    op.create_index(
        'ix_document_extra_costs_document', 'document_extra_costs', ['document_id']
    )
    op.create_index(
        'ix_document_extra_costs_organization_id',
        'document_extra_costs',
        ['organization_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_document_extra_costs_organization_id', 'document_extra_costs')
    op.drop_index('ix_document_extra_costs_document', 'document_extra_costs')
    op.drop_table('document_extra_costs')
