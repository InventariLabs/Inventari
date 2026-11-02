"""create document_profiles table

Revision ID: eccb4efe4301
Revises: 95ebb9252a8d
Create Date: 2026-04-10 20:55:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


# revision identifiers, used by Alembic.
revision: str = 'eccb4efe4301'
down_revision: Union[str, None] = '95ebb9252a8d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'document_profiles',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column(
            'organization_id',
            sa.UUID(),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('value_tracking_enabled', sa.Boolean(), nullable=False, default=False),
        sa.Column('tax_handling', sa.String(length=20), nullable=False, default='NONE'),
        sa.Column('default_tax_rate', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('require_partner_tax_id', sa.Boolean(), nullable=False, default=False),
        sa.Column(
            'numbering_format',
            sa.String(length=100),
            nullable=False,
            default='{TYPE}/{YEAR}/{SEQ:03d}',
        ),
        sa.Column('type_labels', JSON(), nullable=True),
        sa.Column('default_unit', sa.String(length=20), nullable=False, default='pcs'),
        sa.Column('visible_line_fields', JSON(), nullable=True),
        sa.Column('print_template', sa.String(length=50), nullable=False, default='standard'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index(
        'ix_document_profiles_organization_id',
        'document_profiles',
        ['organization_id'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('ix_document_profiles_organization_id', table_name='document_profiles')
    op.drop_table('document_profiles')
