"""A process waiting for the migration lock does not stall the migration holding it.

The migration that holds the lock may build an index with ``CREATE INDEX
CONCURRENTLY``, which waits for every transaction already running in the
database to end. A waiter blocked inside ``pg_advisory_lock`` is such a
transaction, and it ends only when the holder lets go of the lock: neither
moves, and PostgreSQL sees no deadlock, because the lock and the index build
sit on two sessions of one process. ``db upgrade`` run beside a starting
backend (DEPLOYMENT.md, *Updating*, step 6) and a second replica starting
beside the first both wait that way. So a waiter tries the lock and sleeps
between tries, and no statement of its own is running while it waits.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool

from app.cli import _migration_lock
from app.config import settings

pytestmark = pytest.mark.integration

BACKEND = Path(__file__).resolve().parents[2]


def _probe_table() -> str:
    """A name of its own per xdist worker: two runs may overlap in one cluster."""
    return f'migration_lock_probe_{os.environ.get("PYTEST_XDIST_WORKER") or "solo"}'


def test_an_index_built_concurrently_finishes_while_the_cli_waits_for_the_lock(
    setup_test_db, monkeypatch
) -> None:
    monkeypatch.setenv('DATABASE_URL', settings.DATABASE_URL)
    monkeypatch.delenv('MIGRATION_DATABASE_URL', raising=False)
    engine = create_engine(
        settings.DATABASE_URL, poolclass=NullPool, isolation_level='AUTOCOMMIT'
    )
    table = _probe_table()
    holder = builder = None
    acquired = threading.Event()
    thread: threading.Thread | None = None

    def wait_for_the_lock() -> None:
        with _migration_lock.hold_migration_lock():
            acquired.set()

    try:
        builder = engine.connect()
        builder.execute(text(f'DROP TABLE IF EXISTS {table}'))
        builder.execute(text(f'CREATE TABLE {table} (id integer)'))

        # The migration: it holds the lock for the whole of its run.
        holder = engine.connect()
        holder.execute(
            text('SELECT pg_advisory_lock(:key)'),
            {'key': _migration_lock.MIGRATION_LOCK_KEY},
        )
        thread = threading.Thread(target=wait_for_the_lock, daemon=True)
        thread.start()
        assert not acquired.wait(1.0), 'the waiter took a lock the migration holds'

        # The migration's next step, on a session of its own as alembic runs it.
        builder.execute(text("SET statement_timeout = '5s'"))
        try:
            builder.execute(
                text(f'CREATE INDEX CONCURRENTLY ix_{table} ON {table} (id)')
            )
        except OperationalError as exc:
            pytest.fail(
                'CREATE INDEX CONCURRENTLY did not finish while a process waited '
                'for the migration lock: the waiter keeps a statement running '
                'that the build waits for, and the holder never lets go '
                f'({exc.orig})'
            )
    finally:
        if holder is not None:
            holder.execute(
                text('SELECT pg_advisory_unlock(:key)'),
                {'key': _migration_lock.MIGRATION_LOCK_KEY},
            )
            holder.close()
        if thread is not None:
            thread.join(timeout=15)
        if builder is not None:
            builder.execute(text("SET statement_timeout = '0'"))
            builder.execute(text(f'DROP TABLE IF EXISTS {table}'))
            builder.close()
        engine.dispose()

    assert acquired.is_set(), 'the waiter never took the lock once it was free'


def test_the_entrypoint_waits_for_the_lock_the_same_way() -> None:
    """A second replica starting beside the first is the same waiter."""
    source = (BACKEND / 'entrypoint.sh').read_text(encoding='utf-8')
    assert 'pg_advisory_lock(' not in source, (
        'the entrypoint blocks in pg_advisory_lock, so a replica starting '
        'beside one that builds an index concurrently stalls it'
    )
    assert 'wait_for_the_migration_lock' in source
