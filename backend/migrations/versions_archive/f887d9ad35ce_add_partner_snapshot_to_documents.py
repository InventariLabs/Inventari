"""add_partner_snapshot_to_documents

Revision ID: f887d9ad35ce
Revises: 9ec6702ad902
Create Date: 2026-04-12 09:43:29.798879

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f887d9ad35ce'
down_revision: Union[str, None] = '9ec6702ad902'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('partner_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('documents', 'partner_snapshot')
