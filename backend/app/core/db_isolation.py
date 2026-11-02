"""Throwaway databases for migration tests, without the teardown bill.

Migration tests need to upgrade into an empty database. Creating one per test
class and dropping it afterwards is the obvious way to get that, and it was the
single most expensive thing in the suite.

``DROP DATABASE`` issues an immediate checkpoint and waits for it. Under
``pytest -n auto`` that means every teardown blocks until Postgres has flushed
whatever all the other workers just wrote, so the cost scales with worker count
rather than with the test: teardowns of up to 411s on 24 workers, against 2s
when the same file ran alone.

So this hands out one long-lived database per xdist worker and empties it
before each use instead. ``DROP SCHEMA public CASCADE`` forces no checkpoint —
measured at 279ms even on a badly bloated database — and because the wipe
happens on the way *in*, teardown costs nothing at all.

Emptying rather than recreating also keeps ``search_path`` pointing at
``public``, which matters more than it looks: a dozen historical migrations
resolve tables as ``public.<name>``, so a schema-scoped connection would make
their existence guards inspect one namespace while their DDL wrote to another.

The database also belongs to the run that made it: the name wears the run id
(``run_scoped_db_name``) and ``drop_run_databases`` removes it when the run
ends. A run killed outright leaves one orphan per worker, but under a name no
later run can pick up — and the sweep that clears such an orphan has to name
the run it means, so it cannot delete a suite that is still running.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import create_engine, text

from app.config import settings

# Databases this process has already created. Worker-local by construction:
# each xdist worker is its own process, and pytest runs one test at a time
# within a worker, so a single scratch database per worker is enough.
_created: set[str] = set()

# Base name of the scratch databases. It lives here because the name this
# module hands out and the sweep in ``drop_run_databases`` that removes it have
# to agree on it — a disagreement is a leaked database.
_SCRATCH_BASE = 'test_scratch'


def _scratch_db_name() -> str:
    """Name of this worker's scratch database — this run's, and no other's."""
    return run_scoped_db_name(_SCRATCH_BASE, os.environ.get('PYTEST_XDIST_WORKER'))


def _admin_url() -> str:
    """URL of the maintenance database, used to issue CREATE DATABASE."""
    return f'{settings.DATABASE_URL.rsplit("/", 1)[0]}/postgres'


def _ensure_database(name: str) -> None:
    """Create the scratch database once per worker process."""
    if name in _created:
        return
    admin = create_engine(_admin_url(), isolation_level='AUTOCOMMIT')
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text('SELECT 1 FROM pg_database WHERE datname = :n'), {'n': name}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        admin.dispose()
    _created.add(name)


@contextmanager
def isolated_db_url(prefix: str = 'test') -> Iterator[str]:
    """Yield a URL to an empty database, reused across calls in this worker.

    *prefix* is accepted for readability at call sites; the database name comes
    from the worker id and the run id, since one scratch database per worker is
    all a sequential worker can use at a time — and a name that wears the run
    id cannot be mistaken for, or inherited from, another run's leftover.
    """
    name = _scratch_db_name()
    _ensure_database(name)
    url = f'{settings.DATABASE_URL.rsplit("/", 1)[0]}/{name}'

    # Wipe on the way in: DROP SCHEMA forces no checkpoint, so emptying costs
    # 279ms even on a bloated database, while a DROP DATABASE here would block
    # on every other worker's writes. What is left behind is this run's own
    # database under this run's own name, which pytest_sessionfinish drops.
    engine = create_engine(url, isolation_level='AUTOCOMMIT')
    try:
        with engine.connect() as conn:
            conn.execute(text('DROP SCHEMA IF EXISTS public CASCADE'))
            conn.execute(text('CREATE SCHEMA public'))
    finally:
        engine.dispose()

    yield url


def controller_run_id() -> str:
    """This run's identity: minted by the controller, worn by every database
    it creates.

    The controller imports the test configuration before xdist spawns the
    workers, and the workers inherit its environment, so one ``setdefault``
    here gives every process of one run the same id and every process of
    another run a different one. A worker database built on this id can
    therefore never share its name with a database another run created on
    the same server — which is the collision the recovery sweeps feed on:
    the documented remedy for a poisoned run is dropping the run's test
    databases, and such a sweep landing on a server while a suite is still
    running deletes that suite's databases under it, read live as dozens of
    "ERROR at setup — database does not exist" under a summary that still
    counts its passed tests as green.
    """
    return os.environ.setdefault('INVENTARI_TEST_RUN_ID', uuid4().hex[:10])


def run_scoped_db_name(base: str, worker_id: str | None) -> str:
    """A test database name that dies with its run.

    *worker_id* is the xdist worker suffix, or ``None`` for the single-process
    path; either way the name is unique to one run, so a leftover from a
    killed run is inert and a sweep aimed at another run's names is harmless.
    """
    if worker_id:
        return f'{base}_r{controller_run_id()}_{worker_id}'
    return f'{base}_r{controller_run_id()}'


def drop_run_databases(database_url: str, base: str, run_id: str) -> list[str]:
    """Drop every database wearing this run's id, and name what was dropped.

    Two families carry a run id: the worker databases built on *base* and the
    migration scratch databases beside them. Both are this run's to remove —
    the scratch ones were the ones nobody removed, which is how a server
    accumulates a database per worker per suite.

    Only names carrying exactly this run's id can match, so the sweep cannot
    reach a concurrent run's databases. ``WITH (FORCE)`` because a killed
    worker leaves connections behind that an ordinary DROP would refuse.
    """
    admin_url = f'{database_url.rsplit("/", 1)[0]}/postgres'
    prefixes = (f'{base}_r{run_id}', f'{_SCRATCH_BASE}_r{run_id}')
    admin = create_engine(admin_url, isolation_level='AUTOCOMMIT')
    dropped: list[str] = []
    try:
        with admin.connect() as conn:
            for prefix in prefixes:
                names = [
                    row[0]
                    for row in conn.execute(
                        text('SELECT datname FROM pg_database WHERE datname LIKE :p'),
                        {'p': f'{prefix}%'},
                    )
                ]
                for name in names:
                    conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
                    dropped.append(name)
    finally:
        admin.dispose()
    return dropped
