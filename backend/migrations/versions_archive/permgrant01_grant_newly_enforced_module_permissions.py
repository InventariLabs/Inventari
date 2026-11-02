"""grant newly enforced module permissions to existing roles

Revision ID: permgrant01
Revises: invrecipient01
Create Date: 2026-08-23

Nine modules declared permissions that nothing enforced, so every member with
a role row could use all of them regardless of what that role listed. Mounting
the guards makes those keys real — and would, without this, silently take nine
modules away from everyone whose permissions come from a role row rather than
the built-in fallback.

Enforcement is the new thing here, not the grant. Preserving what people can do
today therefore means granting: an administrator who wants a role restricted
can now untick the box, which was never possible before. Built-in roles need
nothing — they resolve module defaults from the manifest at request time.
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = 'permgrant01'
down_revision = 'invrecipient01'
branch_labels = None
depends_on = None

#: Keys that gained an enforcement point in the same change as this migration.
GRANTED = [
    'equipment:read',
    'equipment:write',
    'maker:read',
    'maker:write',
    'shopping_lists:read',
    'shopping_lists:write',
    'stats:read',
    'stock_takes:read',
    'stock_takes:write',
    'recipes:consume',
    'vision:extract',
    'vision:nutrition',
]


def _roles(conn):
    return conn.execute(
        sa.text('SELECT id, permissions FROM roles WHERE is_system = false')
    ).fetchall()


def upgrade() -> None:
    conn = op.get_bind()
    for role_id, permissions in _roles(conn):
        current = list(permissions or [])
        merged = current + [key for key in GRANTED if key not in current]
        if len(merged) == len(current):
            continue
        conn.execute(
            sa.text('UPDATE roles SET permissions = :perms WHERE id = :id'),
            {'perms': json.dumps(merged), 'id': role_id},
        )


def downgrade() -> None:
    """Take the keys back off every custom role.

    Lossy where an administrator ticked one of these deliberately after the
    upgrade — there is no way to tell that apart from the grant this migration
    made, and leaving them would be the more surprising of the two.
    """
    conn = op.get_bind()
    for role_id, permissions in _roles(conn):
        current = list(permissions or [])
        remaining = [key for key in current if key not in GRANTED]
        if len(remaining) == len(current):
            continue
        conn.execute(
            sa.text('UPDATE roles SET permissions = :perms WHERE id = :id'),
            {'perms': json.dumps(remaining), 'id': role_id},
        )
