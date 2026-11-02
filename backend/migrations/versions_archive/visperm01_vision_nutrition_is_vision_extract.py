"""reading a nutrition table off a photograph is vision:extract: carry roles across

Revision ID: visperm01
Revises: modkey01
Create Date: 2026-10-22

The vision module guarded its two photograph readers with two keys:
``vision:extract`` for a product label and ``vision:nutrition`` for a
nutrition table. Both read fields off a photograph, both went to the same
default roles, and the second key existed only because the nutrition reader
came later — "nutrition" is a noun, not an action, and it sat outside the
vocabulary every other permission key is spelled with. The module now
guards both readers with ``vision:extract``, before the first release fixes
the key in every installation.

A role holding ``vision:nutrition`` holds ``vision:extract`` instead, in the
position the old key held; a role that held both keeps one. A custom role
granted only one of the two now reaches both readers — the same act on the
same photograph, which the default roles never told apart.

The downgrade gives ``vision:nutrition`` back to every role holding
``vision:extract``: which of them held it before cannot be told any more,
and the default roles held both.

``audit_log`` records what happened under the name it had and is
append-only; it is left as it is. A data migration of its own, with no
schema change.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = 'visperm01'
down_revision: str | None = 'modkey01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = 'vision:nutrition'
NEW = 'vision:extract'


def _merged(keys: list[str]) -> list[str]:
    out: list[str] = []
    for key in keys:
        key = NEW if key == OLD else key
        if key not in out:
            out.append(key)
    return out


def _split(keys: list[str]) -> list[str]:
    out = [key for key in keys if key != OLD]
    return out + [OLD] if NEW in out else out


def _rewrite(holding: str, rewrite) -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            'SELECT id, permissions FROM roles '
            'WHERE permissions @> CAST(:holding AS JSONB)'
        ),
        {'holding': json.dumps([holding])},
    ).mappings()
    for row in rows.all():
        bind.execute(
            sa.text(
                'UPDATE roles SET permissions = CAST(:permissions AS JSONB) WHERE id = :id'
            ),
            {'id': row['id'], 'permissions': json.dumps(rewrite(row['permissions']))},
        )


def upgrade() -> None:
    # ``--sql`` mode writes the schema script from the revision files alone;
    # there is no connection to read the rows this revision carries across.
    if context.is_offline_mode():
        return
    _rewrite(OLD, _merged)


def downgrade() -> None:
    if context.is_offline_mode():
        return
    _rewrite(NEW, _split)
