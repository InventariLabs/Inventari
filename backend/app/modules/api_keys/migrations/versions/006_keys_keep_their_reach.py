"""give every existing api key the permissions it effectively had.

Before this chain, every key carried one fixed set, and the agent endpoints of
the printing module asked for no permission at all; they now guard
``printing:agent``. So an ordinary key gets the fixed set plus
``printing:agent`` — it could act as a print agent, and still can — and a key
of the ``printing`` scope gets ``printing:agent`` alone, which is exactly the
reach its path prefix gave it. A scope nobody registered opened no path, and
its key gets no permission: it reaches nothing, as before.

The sets are frozen here rather than imported: what a key had on the day of
this revision does not change when the constants do.

Revision ID: 006_keys_keep_their_reach
Revises: 005_key_permissions
Create Date: 2026-10-23

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '006_keys_keep_their_reach'
down_revision: str | None = '005_key_permissions'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORDINARY = [
    'categories:read',
    'items:read',
    'items:write',
    'locations:read',
    'org:read',
    'printing:agent',
]
_SCOPED = {'printing': ['printing:agent']}


def upgrade() -> None:
    # Only rows not yet filled: a table built from current metadata and
    # replayed from 001_initial holds keys that already carry their lists.
    op.execute(
        sa.text(
            'UPDATE api_keys SET permissions = CASE '
            'WHEN scope IS NULL THEN CAST(:ordinary AS JSONB) '
            'WHEN scope = :printing THEN CAST(:printing_set AS JSONB) '
            "ELSE '[]'::jsonb END "
            'WHERE permissions IS NULL'
        ).bindparams(
            ordinary=json.dumps(_ORDINARY),
            printing='printing',
            printing_set=json.dumps(_SCOPED['printing']),
        )
    )
    op.execute(
        sa.text(
            'UPDATE api_keys SET scope_names = CASE '
            "WHEN scope IS NULL THEN '[]'::jsonb "
            'ELSE jsonb_build_array(scope) END '
            'WHERE scope_names IS NULL'
        )
    )


def downgrade() -> None:
    # Nothing to undo: 005's downgrade drops the columns this filled.
    pass
