"""the recipe cover column keeps the storage key, not the built address

Revision ID: 011_image_url_keeps_the_key
Revises: 010_meal_slot_is_text
Create Date: 2026-10-22

``recipes.image_url`` kept the address the current storage backend handed out
(``/uploads/<key>`` locally, a bucket URL under S3), so moving the files or
switching backends rewrote every row. From this revision the column keeps the
org-scoped storage key the upload wrote — ``<org>/recipes/<recipe_id>/cover.<ext>``
— and the address is built when the row is read (``Recipe.image_url``).

Rows written before it are rewritten here from both address forms. An absolute
address that is not ours (a picture kept from an import) is left alone; the
column keeps its name and only what it holds changes. The reverse rewrites
keys into the local backend's ``/uploads/<key>`` form.

Core keeps its own revision for the core tables: the two chains are
independent.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '011_image_url_keeps_the_key'
down_revision: Union[str, None] = '010_meal_slot_is_text'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: The tail of a URL that is a key under our namespace: a UUID, the family
#: segment and the leaf, up to the end or a query string. Only an address
#: carrying one of these family names after a UUID is one of ours; anything
#: else is a foreign link and is kept.
_KEY_TAIL = (
    '([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
    '/(items|recipes|organizations|attachments|equipment)/[^?#]+)'
)

_UPGRADE_SQL: tuple[str, ...] = (
    # Local backend: ``/uploads/<key>`` is our route with the key under it.
    "UPDATE recipes SET image_url = substring(image_url from length('/uploads/') + 1) "
    "WHERE image_url LIKE '/uploads/%'",
    # S3 backends: both the custom-endpoint and the AWS virtual-host form end
    # with the key; the bucket and endpoint before it vary by install.
    "UPDATE recipes SET image_url = substring(image_url from '"
    + _KEY_TAIL
    + "') WHERE image_url ~ '^https?://' AND image_url ~ '"
    + _KEY_TAIL
    + "'",
)

_DOWNGRADE_SQL: tuple[str, ...] = (
    "UPDATE recipes SET image_url = '/uploads/' || image_url "
    "WHERE image_url IS NOT NULL AND image_url NOT LIKE '/uploads/%' "
    "AND image_url NOT LIKE 'http%'",
)


def _run_upgrade_sql(bind: sa.engine.Connection | sa.engine.Engine) -> None:
    """Rewrite the address forms into storage keys; kept callable for tests.

    ``bind`` may be a ``Session.get_bind()`` Engine (which has no ``execute``
    in SQLAlchemy 2.0 and gets its own transaction) or a live connection —
    alembic's own bind or a test's — whose transaction the caller owns.
    """
    if isinstance(bind, sa.engine.Engine):
        with bind.begin() as connection:
            _execute(connection, _UPGRADE_SQL)
        return
    _execute(bind, _UPGRADE_SQL)


def _run_downgrade_sql(bind: sa.engine.Connection | sa.engine.Engine) -> None:
    """Rewrite keys into the local backend's address form."""
    if isinstance(bind, sa.engine.Engine):
        with bind.begin() as connection:
            _execute(connection, _DOWNGRADE_SQL)
        return
    _execute(bind, _DOWNGRADE_SQL)


def _execute(
    connection: sa.engine.Connection, statements: tuple[str, ...]
) -> None:
    for statement in statements:
        connection.execute(sa.text(statement))


def upgrade() -> None:
    _run_upgrade_sql(op.get_bind())


def downgrade() -> None:
    _run_downgrade_sql(op.get_bind())
