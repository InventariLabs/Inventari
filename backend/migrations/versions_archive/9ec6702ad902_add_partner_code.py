"""add_partner_code

Revision ID: 9ec6702ad902
Revises: 64a87ebd2b3a
Create Date: 2026-04-12 09:40:32.762776

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9ec6702ad902'
down_revision: Union[str, None] = '64a87ebd2b3a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('partners', sa.Column('code', sa.String(length=50), nullable=True))
    op.create_index(op.f('ix_partners_code'), 'partners', ['code'], unique=False)
    op.create_index('uq_partner_org_code', 'partners', ['organization_id', 'code'], unique=True, postgresql_where=sa.text('code IS NOT NULL'))


def downgrade() -> None:
    op.drop_index('uq_partner_org_code', table_name='partners', postgresql_where=sa.text('code IS NOT NULL'))
    op.drop_index(op.f('ix_partners_code'), table_name='partners')
    op.drop_column('partners', 'code')
