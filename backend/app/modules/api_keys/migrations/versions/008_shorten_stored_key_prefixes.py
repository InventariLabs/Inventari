"""cut every stored key prefix down to what identifies the key.

A key's prefix was its first 20 characters: ``inv_live_`` and 11 of the 32
random ones. It is shown on the API keys page and written into the journal, so
whoever may read the journal held a third of each key for no purpose: telling
an organization's few keys apart takes six.

Nothing authenticates by the prefix. A key is found by the hash of its whole
value, which this leaves alone, so every key keeps working. A revoked key's row
is cut as well: it stays in the table, and nothing needs the longer form of it.

Reversible only as far as the data allows. The cut characters are stored
nowhere else, so a downgrade leaves these keys on the short prefix, which the
wider column holds and nothing depends on. Journal entries are not touched
here: the journal is immutable, and an entry keeps the prefix it was written
with, which still begins with the short one.

The length is frozen here rather than imported: what this revision cuts to does
not change when the constant does.

Revision ID: 008_shorten_stored_key_prefixes
Revises: 007_scope_names_replace_scope
Create Date: 2026-11-05

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '008_shorten_stored_key_prefixes'
down_revision: str | None = '007_scope_names_replace_scope'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SHOWN_LENGTH = 15


def upgrade() -> None:
    op.execute(
        sa.text(
            'UPDATE api_keys SET key_prefix = left(key_prefix, :shown) '
            'WHERE length(key_prefix) > :shown'
        ).bindparams(shown=_SHOWN_LENGTH)
    )


def downgrade() -> None:
    """Nothing to put back: the characters the upgrade cut are stored nowhere."""
