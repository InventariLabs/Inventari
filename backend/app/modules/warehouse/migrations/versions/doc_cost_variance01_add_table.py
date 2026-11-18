"""add document_cost_variances table (a delivery cost that reached no product).

Revision ID: doc_cost_variance01
Revises: doc_print_snapshot01
Create Date: 2026-11-18

A freight bill that arrives after a receipt is posted has nowhere to go, so
it was refused. The amount is still a fact about the delivery; the table keeps
it with its reason and the day it belongs to, apart from every stock value.

Downgrade drops the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_cost_variance01'
down_revision: str | None = 'doc_print_snapshot01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'document_cost_variances',
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
        sa.Column('reason', sa.String(length=255), nullable=False),
        sa.Column('occurred_on', sa.Date(), nullable=False),
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
        sa.CheckConstraint('amount > 0', name='ck_document_cost_variances_amount'),
    )
    op.create_index(
        'ix_document_cost_variances_document',
        'document_cost_variances',
        ['document_id'],
    )
    op.create_index(
        'ix_document_cost_variances_org_date',
        'document_cost_variances',
        ['organization_id', 'occurred_on'],
    )


def downgrade() -> None:
    op.drop_index('ix_document_cost_variances_org_date', 'document_cost_variances')
    op.drop_index('ix_document_cost_variances_document', 'document_cost_variances')
    op.drop_table('document_cost_variances')
