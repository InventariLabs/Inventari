"""Idempotent DDL for module baseline migrations.

A module's ``001_initial`` does not only run on empty databases. On instances
that predate the module-migration split, the core ``baseline_001`` already
created those tables, and ``db upgrade-modules`` reconciles the two by stamping
``001_initial`` — but only when it can see that every table is there. Anything
that confuses that check (a table renamed, a stamp that never happened, DDL
applied by hand) leaves the migration to run against a schema that already
exists, which used to mean ``relation already exists`` on every restart.

Guarding the create calls makes the baseline safe to re-run: it fills in what is
missing and leaves what is there alone. Only ``001_initial`` migrations should
use these. Later revisions carry real schema changes, and silently skipping one
would hide a failed upgrade instead of reporting it — ``db doctor`` is what
catches that case.

The signatures mirror ``op.create_table`` / ``op.create_index`` and are frozen:
migrations already committed call into here, so a change would rewrite history.

**This module is a frozen, additive-only API.** It is the one piece of
application code a revision may import: a fresh installation replays every
revision from the first, so a public name that is renamed, removed or changed
in behaviour breaks installs that have nothing to do with the change. Add new
helpers freely; never alter an existing one. Anything else a revision needs —
a model's columns, a seed list, an inference map — it freezes inside its own
file, the way ``tzaware01`` freezes its column list. A test
(``test_migrations_import_no_application_code``) keeps the public names and
refuses any other ``app`` import in a revision.

``convert_naive_timestamps_to_utc`` is the one helper here meant for later
revisions: its guard is not "the DDL is already there" but "the column already
has the type the models declare", so on a database that is already right it has
nothing to do, and on one that is not it always acts.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any

import sqlalchemy as sa
from alembic import op
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

#: The scheme settings secrets were written with when ``aiconn02`` was cut,
#: frozen here: ``enc:`` + Fernet, keyed by PBKDF2-HMAC-SHA256 over
#: ``ENCRYPTION_KEY`` (``SECRET_KEY`` when unset) and ``FERNET_SALT``.
_CIPHERTEXT_PREFIX = 'enc:'
_SECRET_KDF_ITERATIONS = 600_000


def relation_exists(name: str) -> bool:
    """True if a table, index or other relation of this name exists in ``public``.

    ``to_regclass`` returns NULL instead of raising for a missing relation, which
    is what makes it usable as a plain existence check.
    """
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text('SELECT to_regclass(:name)'), {'name': f'public.{name}'}
        ).scalar()
    )


def create_table_if_absent(table_name: str, *columns: Any, **kwargs: Any) -> None:
    """``op.create_table``, skipped when the table is already there."""
    if relation_exists(table_name):
        return
    op.create_table(table_name, *columns, **kwargs)


def create_index_if_absent(index_name: str, *args: Any, **kwargs: Any) -> None:
    """``op.create_index``, skipped when the index is already there.

    Indexes are guarded separately from their table: a table restored from a
    partial backup, or created by an older core migration that predates an
    index, has the one without the other.
    """
    if relation_exists(index_name):
        return
    op.create_index(index_name, *args, **kwargs)


def convert_naive_timestamps_to_utc(
    columns: Mapping[str, Sequence[str]],
) -> list[tuple[str, str]]:
    """Make each listed ``timestamp without time zone`` column ``timestamptz``.

    ``columns`` maps a table to the columns its model declares
    ``DateTime(timezone=True)``. Only those the live database holds naive are
    altered; a missing table or column, or one that is already aware, is left
    alone. The stored values are read as UTC — what the application wrote —
    through an explicit ``AT TIME ZONE 'UTC'``: a plain cast would read them in
    the session's time zone and move every instant by its offset.

    One ``ALTER TABLE`` per table, so a table with several naive columns is
    rewritten once. Returns the converted ``(table, column)`` pairs.

    Offline (``--sql``) there is no database to ask, so the script gets one
    ``DO`` block per column that checks the type on the server instead, and
    the return value is empty: what will be converted is decided when the
    script runs.
    """
    if op.get_context().as_sql:
        for table, table_columns in columns.items():
            for column in table_columns:
                op.execute(_GUARDED_CONVERSION.bindparams(table=table, column=column))
        return []

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            'SELECT table_name, column_name FROM information_schema.columns '
            'WHERE table_schema = current_schema() '
            "AND data_type = 'timestamp without time zone' "
            'AND table_name = ANY(:tables)'
        ),
        {'tables': list(columns)},
    ).fetchall()
    naive: dict[str, list[str]] = {}
    for table, column in rows:
        if column in columns[table]:
            naive.setdefault(table, []).append(column)

    converted: list[tuple[str, str]] = []
    for table in sorted(naive):
        clauses = ', '.join(
            f'ALTER COLUMN "{column}" TYPE timestamptz'
            f' USING "{column}" AT TIME ZONE \'UTC\''
            for column in sorted(naive[table])
        )
        op.execute(f'ALTER TABLE "{table}" {clauses}')
        converted.extend((table, column) for column in sorted(naive[table]))
    if converted:
        logger.info(
            'Converted %d naive timestamp column(s) to timestamptz: %s',
            len(converted),
            ', '.join(f'{table}.{column}' for table, column in converted),
        )
    return converted


#: The conversion of one column as a ``DO`` block, a no-op unless the server
#: reports it naive. The names arrive as bound values and reach the ``ALTER``
#: through ``format('%I')``, so the statement text itself is constant.
_GUARDED_CONVERSION = sa.text(
    'DO $$ BEGIN '
    'IF EXISTS (SELECT 1 FROM information_schema.columns '
    'WHERE table_schema = current_schema() '
    'AND table_name = :table AND column_name = :column '
    "AND data_type = 'timestamp without time zone') THEN "
    "EXECUTE format('ALTER TABLE %I ALTER COLUMN %I TYPE timestamptz "
    "USING %I AT TIME ZONE ''UTC''', :table, :column, :column); "
    'END IF; END $$'
)


@lru_cache(maxsize=1)
def _secret_fernet() -> Fernet:
    # Imported here, not at module level: ``app.config`` validates the
    # environment as a side effect of the import, which a revision that never
    # encrypts anything should not trigger.
    from app.config import settings

    material = settings.ENCRYPTION_KEY or settings.SECRET_KEY
    key = hashlib.pbkdf2_hmac(
        'sha256',
        material.encode(),
        settings.FERNET_SALT.encode('utf-8'),
        _SECRET_KDF_ITERATIONS,
    )
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(value: str) -> str:
    """Encrypt a plain-text settings secret as ``enc:<ciphertext>``.

    The scheme the application reads with ``decrypt_value``, frozen so a
    revision that stores a secret does not import the crypto service. Empty and
    already-encrypted values are returned unchanged, so a replay is harmless.
    """
    if not value or value.startswith(_CIPHERTEXT_PREFIX):
        return value
    return _CIPHERTEXT_PREFIX + _secret_fernet().encrypt(value.encode()).decode()
