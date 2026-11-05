"""narrow api_keys.key_prefix to the short form it now holds.

Revision ID: 009_key_prefix_column_narrows
Revises: 008_shorten_stored_key_prefixes
Create Date: 2026-11-05

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '009_key_prefix_column_narrows'
down_revision: str | None = '008_shorten_stored_key_prefixes'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        'api_keys',
        'key_prefix',
        type_=sa.String(15),
        existing_type=sa.String(20),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        'api_keys',
        'key_prefix',
        type_=sa.String(20),
        existing_type=sa.String(15),
        existing_nullable=False,
    )
