"""add the permissions and scope_names columns to api_keys.

A key carries its own permission list, chosen when it is issued, and a list of
scopes bound to permissions instead of the one ``scope`` matched on URL
prefixes. Both arrive nullable here; ``006`` fills them for the keys that
exist, and ``007`` makes them required and drops ``scope``.

Revision ID: 005_key_permissions
Revises: 004_timestamps_carry_their_zone
Create Date: 2026-10-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '005_key_permissions'
down_revision: str | None = '004_timestamps_carry_their_zone'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `IF NOT EXISTS`, for the reason 003 adds with it: a table built from
    # current metadata already has both columns when `db upgrade-modules`
    # replays the chain from 001_initial over it.
    op.execute(
        sa.text('ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS permissions JSONB')
    )
    op.execute(
        sa.text('ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS scope_names JSONB')
    )


def downgrade() -> None:
    op.drop_column('api_keys', 'scope_names')
    op.drop_column('api_keys', 'permissions')
