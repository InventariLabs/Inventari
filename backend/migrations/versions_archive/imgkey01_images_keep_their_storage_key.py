"""image columns keep the storage key, not the address the backend built

Revision ID: imgkey01
Revises: visperm01
Create Date: 2026-10-22

Row image columns kept the address the current storage backend handed out:
``/uploads/<key>`` under the local backend, ``{endpoint}/{bucket}/<key>`` or
``{bucket}.s3.{region}.amazonaws.com/<key>`` under S3. Moving the files or
switching backends therefore meant rewriting every row, although
``docs/SCALING.md`` calls the backend a configuration switch.

From this revision the columns keep the reference instead — the org-scoped
storage key ``<org>/<module>/<relative>`` the upload wrote — and the address a
reader is given is built when the row is read. Rows written before it are
rewritten here from both address forms; an absolute address that is not ours
(a product photo kept from another catalogue) is left alone.

The columns keep their names; only what they hold changes. The reverse
rewrites keys into the local backend's ``/uploads/<key>`` form, which is the
only address a downgrade can know.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'imgkey01'
down_revision: Union[str, None] = 'visperm01'
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

#: ``(table, column)`` pairs this revision owns. The recipes module keeps its
#: own revision for ``recipes.image_url``: core and module chains are
#: independent, and a table a module owns is carried by that module's chain.
_UPGRADE_SQL: tuple[str, ...] = (
    # Local backend: ``/uploads/<key>`` is our route with the key under it.
    "UPDATE items SET image_url = substring(image_url from length('/uploads/') + 1) "
    "WHERE image_url LIKE '/uploads/%'",
    # S3 backends: both the custom-endpoint and the AWS virtual-host form end
    # with the key; the bucket and endpoint before it vary by install.
    "UPDATE items SET image_url = substring(image_url from '"
    + _KEY_TAIL
    + "') WHERE image_url ~ '^https?://' AND image_url ~ '"
    + _KEY_TAIL
    + "'",
    'UPDATE product_templates '
    "SET image_url = substring(image_url from length('/uploads/') + 1) "
    "WHERE image_url LIKE '/uploads/%'",
    "UPDATE product_templates SET image_url = substring(image_url from '"
    + _KEY_TAIL
    + "') WHERE image_url ~ '^https?://' AND image_url ~ '"
    + _KEY_TAIL
    + "'",
)

_DOWNGRADE_SQL: tuple[str, ...] = (
    "UPDATE items SET image_url = '/uploads/' || image_url "
    "WHERE image_url IS NOT NULL AND image_url NOT LIKE '/uploads/%' "
    "AND image_url NOT LIKE 'http%'",
    "UPDATE product_templates SET image_url = '/uploads/' || image_url "
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
