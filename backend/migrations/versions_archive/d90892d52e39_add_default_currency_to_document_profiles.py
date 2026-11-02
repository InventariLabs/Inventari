"""add default_currency to document_profiles

Revision ID: d90892d52e39
Revises: eccb4efe4301
Create Date: 2026-04-10 21:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd90892d52e39'
down_revision: Union[str, None] = 'eccb4efe4301'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'document_profiles',
        sa.Column('default_currency', sa.String(3), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('document_profiles', 'default_currency')
