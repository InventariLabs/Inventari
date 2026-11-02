"""add scopes to api_keys

Revision ID: f7a67cdf1d33
Revises: bc6f28479302
Create Date: 2026-05-09 20:39:34.618124

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f7a67cdf1d33'
down_revision: Union[str, None] = 'bc6f28479302'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'api_keys',
        sa.Column(
            'scopes',
            postgresql.JSON(astext_type=sa.Text()),
            server_default='["read", "write"]',
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column('api_keys', 'scopes')
