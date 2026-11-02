"""make the key's lists required and drop the single scope column.

Revision ID: 007_scope_names_replace_scope
Revises: 006_keys_keep_their_reach
Create Date: 2026-10-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '007_scope_names_replace_scope'
down_revision: str | None = '006_keys_keep_their_reach'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in ('permissions', 'scope_names'):
        op.alter_column(
            'api_keys', column, nullable=False, server_default=sa.text("'[]'::jsonb")
        )
    # `IF EXISTS`: a table built from current metadata never had it, though
    # 003 adds it back when the chain is replayed over such a table.
    op.execute(sa.text('ALTER TABLE api_keys DROP COLUMN IF EXISTS scope'))


def downgrade() -> None:
    # A key keeps its first scope: the old column held one. Its permission
    # list goes with 005's downgrade.
    op.add_column('api_keys', sa.Column('scope', sa.String(32), nullable=True))
    op.execute(sa.text('UPDATE api_keys SET scope = scope_names ->> 0'))
    for column in ('permissions', 'scope_names'):
        op.alter_column('api_keys', column, nullable=True, server_default=None)
