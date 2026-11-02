"""The advisory lock that keeps a schema rebuild and a migration apart.

PostgreSQL holds no lock across "drop the schema and put it back": a demo
rebuild is several statements, and a backend starting beside it runs
``alembic upgrade`` in a process of its own. The rebuild's first statement is
the sweep in ``_reset_sweep``, which ends every session of the application
role — and a migration caught by it loses its connection mid-DDL, exits the
entrypoint non-zero and restarts into a second migration pass.

The backend's entrypoint already serialises replica migrations on an advisory
lock (``docs/SCALING.md``). A rebuild takes the same lock for its whole
destructive part, so a rebuild and a starting backend queue behind each other:
whichever begins first finishes, and the other runs against the schema it
left.

Background jobs ask the same lock before each tick (``app.core.schema_rebuild``),
so they pause for the rebuild instead of reading the schema while it is gone.

The name the lock session carries is also what tells the sweep which session
it may not terminate. A backend waiting for this lock is not one of "every
other session of the role"; ending it is the crash the lock exists to
prevent, so the sweep spares the name while the rebuild holds the key.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from app.core.schema_rebuild import MIGRATION_LOCK_KEY

#: What a session waiting for or holding the lock calls itself in
#: ``pg_stat_activity``. The reset sweep spares it, so it must be the one name
#: the entrypoint and ``hold_migration_lock`` both connect with.
MIGRATION_LOCK_APPLICATION_NAME = 'inventari-migration'


def migration_database_url() -> str | None:
    """The direct-to-Postgres URL the advisory lock has to be taken on.

    ``MIGRATION_DATABASE_URL`` when it is set, because a session-scoped lock
    taken through a transaction-mode pooler can outlive its client on a server
    connection nothing will unlock (§1.2 of ``docs/SCALING.md``).
    ``DATABASE_URL`` is the fallback the entrypoint uses and a development
    stack makes safe by connecting straight to Postgres.
    """
    return os.getenv('MIGRATION_DATABASE_URL') or os.getenv('DATABASE_URL')


@contextmanager
def hold_migration_lock() -> Iterator[None]:
    """Take the migration lock for the duration of the block.

    The caller must be about to change the schema — a rebuild, not a request.
    Whatever another process is migrating is finished before the block starts,
    and a backend that starts during it waits here instead of running its
    migrations against a schema that is halfway rebuilt.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    database_url = migration_database_url()
    if not database_url:
        raise RuntimeError(
            'neither MIGRATION_DATABASE_URL nor DATABASE_URL is set, so there '
            'is no database to take the migration lock on'
        )

    # NullPool: the connection is closed on check-in, so the session-scoped
    # lock cannot sit on a pooled server connection nobody will unlock.
    engine = create_engine(
        database_url,
        poolclass=NullPool,
        connect_args={'application_name': MIGRATION_LOCK_APPLICATION_NAME},
    )
    try:
        with engine.connect() as connection:
            connection = connection.execution_options(isolation_level='AUTOCOMMIT')
            connection.execute(
                text('SELECT pg_advisory_lock(:key)'), {'key': MIGRATION_LOCK_KEY}
            )
            try:
                yield
            finally:
                connection.execute(
                    text('SELECT pg_advisory_unlock(:key)'),
                    {'key': MIGRATION_LOCK_KEY},
                )
    finally:
        engine.dispose()
