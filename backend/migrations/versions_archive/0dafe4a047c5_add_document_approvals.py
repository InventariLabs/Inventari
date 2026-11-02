"""add document_approvals and approval fields to profile

Revision ID: 0dafe4a047c5
Revises: 3e84b62c8749
Create Date: 2026-04-25 12:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0dafe4a047c5'
down_revision: Union[str, None] = 'dce8a56741b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'document_approvals',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('document_id', sa.UUID(), nullable=False),
        sa.Column('requested_by', sa.UUID(), nullable=False),
        sa.Column('approver_user_id', sa.UUID(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='PENDING'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['approver_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('document_id'),
    )
    op.create_index('ix_document_approvals_doc', 'document_approvals', ['document_id'])

    op.add_column('document_profiles', sa.Column('approval_threshold', sa.Numeric(14, 2), nullable=True))
    op.add_column('document_profiles', sa.Column('approval_required_for_types', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('document_profiles', 'approval_required_for_types')
    op.drop_column('document_profiles', 'approval_threshold')
    op.drop_index('ix_document_approvals_doc', table_name='document_approvals')
    op.drop_table('document_approvals')
