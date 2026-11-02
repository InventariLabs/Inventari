"""add document_packages and document_package_lines tables (packing a dispatch).

Revision ID: doc_packages01
Revises: doc_tzaware01
Create Date: 2026-10-16

Packing goes between "all picked" and completion: the picked goods of a
dispatch are put into packages, each numbered within its document and
optionally weighed, and each package records how much of which document line
it holds. The packing slip and the package label print the same package code,
so the carrier's label and the slip can be matched.

Downgrade drops both tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_packages01'
down_revision: str | None = 'doc_tzaware01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'document_packages',
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
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('weight_kg', sa.Numeric(10, 3), nullable=True),
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
        sa.UniqueConstraint(
            'document_id', 'number', name='uq_document_packages_number'
        ),
        sa.CheckConstraint('weight_kg > 0', name='ck_document_packages_weight'),
    )
    op.create_index(
        'ix_document_packages_organization_id',
        'document_packages',
        ['organization_id'],
    )
    op.create_index(
        'ix_document_packages_document_id', 'document_packages', ['document_id']
    )

    op.create_table(
        'document_package_lines',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column(
            'document_package_id',
            sa.UUID(),
            sa.ForeignKey('document_packages.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'document_line_id',
            sa.UUID(),
            sa.ForeignKey('document_lines.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('quantity', sa.Numeric(12, 3), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            'document_package_id',
            'document_line_id',
            name='uq_document_package_lines_line',
        ),
        sa.CheckConstraint('quantity > 0', name='ck_document_package_lines_quantity'),
    )
    op.create_index(
        'ix_document_package_lines_document_package_id',
        'document_package_lines',
        ['document_package_id'],
    )
    op.create_index(
        'ix_document_package_lines_document_line_id',
        'document_package_lines',
        ['document_line_id'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_document_package_lines_document_line_id', 'document_package_lines'
    )
    op.drop_index(
        'ix_document_package_lines_document_package_id', 'document_package_lines'
    )
    op.drop_table('document_package_lines')
    op.drop_index('ix_document_packages_document_id', 'document_packages')
    op.drop_index('ix_document_packages_organization_id', 'document_packages')
    op.drop_table('document_packages')
