"""The reset sweep ends only the sessions this role is allowed to terminate.

Two commands empty the database before they rebuild it: ``db reset`` and the
nightly demo rebuild. Each ran ``pg_terminate_backend`` over the database first,
and written as "every session here" the sweep walks into a rule PostgreSQL
does not bend — measured on a running server, as a role without SUPERUSER
while a superuser held a session in the same database::

    SELECT pg_terminate_backend(pid) FROM pg_stat_activity
     WHERE datname = current_database() AND pid <> pg_backend_pid();
    ERROR:  permission denied to terminate process
    DETAIL:  Only roles with the SUPERUSER attribute may terminate
             processes of roles with the SUPERUSER attribute.

The error aborts the statement, so the reset stops before ``DROP SCHEMA``:
on a prod-shaped stack — ``db-backup``'s ``pg_dump`` at 02:00, an operator's
``psql`` — the rebuild keeps yesterday's data. The same sweep with
``AND usename = current_user`` ends the sessions of its own role, which are
the ones it must clear to take the schema, and never reaches a session it may
not.

So the statement is written once, in ``app.cli._reset_sweep``, and the tests
here pin both halves: the sweep still ends what it should, it no longer
touches what it must not, and no reset command writes a copy of its own.
"""

from __future__ import annotations

import contextlib
import inspect
import os
import threading
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from app.cli import _migration_lock, _reset_sweep, commands_db, commands_demo
from app.config import settings

pytestmark = pytest.mark.integration

BACKEND = Path(__file__).resolve().parents[2]

#: A throwaway login for the probe below. Not a secret — a password
#: PostgreSQL will authenticate for a role nothing else ever uses.
_PROBE_AUTH = 'reset-sweep-probe-not-a-secret'


def _worker_tag() -> str:
    """A name of its own per xdist worker: two runs may overlap in one cluster."""
    return os.environ.get('PYTEST_XDIST_WORKER') or 'solo'


def _probe_role() -> str:
    return f'inventari_sweep_probe_{_worker_tag()}'


class TestTheSweepStaysInsideTheAppRole:
    def test_it_ends_sessions_of_its_own_role_and_leaves_everyone_elses(
        self, setup_test_db
    ) -> None:
        # ``setup_test_db`` is what makes this worker's database exist at all.
        probe = _probe_role()
        owner = create_engine(settings.DATABASE_URL, poolclass=NullPool)
        probe_engine = create_engine(
            make_url(settings.DATABASE_URL).set(username=probe, password=_PROBE_AUTH),
            poolclass=NullPool,
        )
        holder = twin = sweeper = None
        try:
            with owner.begin() as conn:
                assert conn.execute(
                    text('SELECT rolsuper FROM pg_roles WHERE rolname = current_user')
                ).scalar(), (
                    'a superuser has to run this: only then is its own session '
                    'out of the probe\u2019s reach, and that is the difference the '
                    'predicate makes. Under a non-superuser both directions '
                    'would pass and the test would prove nothing.'
                )
                conn.execute(text(f'DROP ROLE IF EXISTS {probe}'))
                conn.execute(
                    text(f'CREATE ROLE {probe} LOGIN PASSWORD :auth'),
                    {'auth': _PROBE_AUTH},
                )

            holder = owner.connect()
            twin = probe_engine.connect()
            sweeper = probe_engine.connect()

            rows = sweeper.execute(
                text(_reset_sweep.TERMINATE_OTHER_SESSIONS_SQL),
                _reset_sweep.TERMINATE_OTHER_SESSIONS_PARAMS,
            ).fetchall()

            assert [row[0] for row in rows] == [True], (
                f'the sweep returned {rows}; it must end exactly one session — '
                'the probe, the one it has the right to end — and no other'
            )
            assert holder.execute(text('SELECT 1')).scalar() == 1, (
                'the session of the role that owns the database did not survive '
                'a sweep it was never part of'
            )
        finally:
            for connection in (sweeper, twin, holder):
                if connection is not None:
                    # The sweep may have just terminated this connection.
                    with contextlib.suppress(Exception):
                        connection.close()
            owner.dispose()
            probe_engine.dispose()
            with owner.begin() as conn:
                conn.execute(text(f'DROP ROLE IF EXISTS {probe}'))

    def test_the_sweep_is_not_written_again_by_any_reset_command(self) -> None:
        """One definition — otherwise the predicate drifts back out of one of them."""
        for module in (commands_db, commands_demo):
            source = inspect.getsource(module)
            assert 'pg_terminate_backend' not in source, (
                f'{module.__name__} writes the sweep itself; run the one in '
                'app.cli._reset_sweep instead, so the predicate a role without '
                'SUPERUSER needs stays in one place'
            )
            assert 'TERMINATE_OTHER_SESSIONS_SQL' in source, (
                f'{module.__name__} no longer runs the shared sweep at all'
            )


class TestTheSweepSparesTheMigrationLock:
    """A backend waiting for the migration lock must survive the sweep.

    The demo's first rebuild starts at the same moment as the backend, and the
    entrypoint holds the advisory lock while it migrates. That session is
    another session of the same role, so the sweep ended it like any other;
    the entrypoint then exited non-zero on its next statement and
    ``restart: unless-stopped`` ran every migration a second time. The reset
    now holds the same lock for its rebuild, so the session it spares is
    waiting, not mid-DDL.
    """

    def test_it_ends_no_session_of_the_migration_lock(self, setup_test_db) -> None:
        probe = _probe_role()
        owner = create_engine(settings.DATABASE_URL, poolclass=NullPool)
        lock_engine = create_engine(
            make_url(settings.DATABASE_URL).set(username=probe, password=_PROBE_AUTH),
            poolclass=NullPool,
            connect_args={
                'application_name': _migration_lock.MIGRATION_LOCK_APPLICATION_NAME
            },
        )
        sweeper_engine = create_engine(
            make_url(settings.DATABASE_URL).set(username=probe, password=_PROBE_AUTH),
            poolclass=NullPool,
        )
        holder = sweeper = None
        try:
            with owner.begin() as conn:
                conn.execute(text(f'DROP ROLE IF EXISTS {probe}'))
                conn.execute(
                    text(f'CREATE ROLE {probe} LOGIN PASSWORD :auth'),
                    {'auth': _PROBE_AUTH},
                )

            holder = lock_engine.connect()
            holder.execute(
                text('SELECT pg_advisory_lock(:key)'),
                {'key': _migration_lock.MIGRATION_LOCK_KEY},
            )
            sweeper = sweeper_engine.connect()

            rows = sweeper.execute(
                text(_reset_sweep.TERMINATE_OTHER_SESSIONS_SQL),
                _reset_sweep.TERMINATE_OTHER_SESSIONS_PARAMS,
            ).fetchall()

            assert rows == [], (
                f'the sweep ended {len(rows)} session(s) of the migration lock; '
                'a backend waiting there would exit and restart into a second '
                'migration pass'
            )
            assert holder.execute(text('SELECT 1')).scalar() == 1, (
                'the session holding the migration lock was terminated'
            )
            granted = sweeper.execute(
                text(
                    'SELECT count(*) FROM pg_locks '
                    "WHERE locktype = 'advisory' "
                    'AND objid = :key AND granted AND pid = :pid'
                ),
                {
                    'key': _migration_lock.MIGRATION_LOCK_KEY,
                    'pid': holder.execute(text('SELECT pg_backend_pid()')).scalar(),
                },
            ).scalar()
            assert granted == 1, (
                'the sweep released the migration lock, so a second replica '
                'could migrate while the first still is'
            )
        finally:
            for connection in (sweeper, holder):
                if connection is not None:
                    with contextlib.suppress(Exception):
                        connection.close()
            owner.dispose()
            lock_engine.dispose()
            sweeper_engine.dispose()
            with owner.begin() as conn:
                conn.execute(text(f'DROP ROLE IF EXISTS {probe}'))


class TestTheRebuildQueuesBehindAMigration:
    """The lock is what makes sparing the session safe, so the reset takes it.

    A sweep that spares a migration session without holding the key itself
    would drop the schema under a running migration. The rebuild therefore
    starts by taking the entrypoint's lock, and waits for a migration in
    progress rather than running beside it.
    """

    def test_it_waits_for_the_lock_a_migration_holds(
        self, setup_test_db, monkeypatch
    ) -> None:
        monkeypatch.setenv('DATABASE_URL', settings.DATABASE_URL)
        monkeypatch.delenv('MIGRATION_DATABASE_URL', raising=False)
        holder_engine = create_engine(settings.DATABASE_URL, poolclass=NullPool)
        holder = holder_engine.connect()
        acquired = threading.Event()
        thread: threading.Thread | None = None

        def take_the_lock() -> None:
            with _migration_lock.hold_migration_lock():
                acquired.set()

        try:
            holder.execute(
                text('SELECT pg_advisory_lock(:key)'),
                {'key': _migration_lock.MIGRATION_LOCK_KEY},
            )
            thread = threading.Thread(target=take_the_lock, daemon=True)
            thread.start()
            assert not acquired.wait(0.5), (
                'the rebuild took the migration lock while a migration held it'
            )
        finally:
            holder.execute(
                text('SELECT pg_advisory_unlock(:key)'),
                {'key': _migration_lock.MIGRATION_LOCK_KEY},
            )
            holder.close()
            holder_engine.dispose()
            if thread is not None:
                thread.join(timeout=10)

        assert acquired.is_set(), (
            'the rebuild never took the migration lock once it was free, so '
            'it would migrate beside the next backend that starts'
        )


class TestTheEntrypointCarriesTheNameTheSweepSpares:
    def test_the_lock_session_is_named_with_the_shared_constant(self) -> None:
        """A shell script is beyond the test suite; its one line is pinned here.

        The sweep spares an application name that nothing sets only if this
        line is gone, and the failure it prevents is a restart into a second
        migration pass — visible only on a real demo deploy.
        """
        source = (BACKEND / 'entrypoint.sh').read_text(encoding='utf-8')

        assert 'from app.cli._migration_lock import' in source, (
            'the entrypoint no longer takes its lock name from the module the '
            'sweep reads it from'
        )
        assert 'application_name=MIGRATION_LOCK_APPLICATION_NAME' in source, (
            'the entrypoint does not name its migration session, so the sweep '
            'cannot tell it from a session it may terminate'
        )


@contextlib.contextmanager
def _a_database_the_probe_owns(
    monkeypatch: pytest.MonkeyPatch, *, expect_empty: bool = True
):
    """A scratch database the probe role owns, with a superuser session in it.

    That is the shape of a prod-shaped stack in the middle of a reset: the
    application role owns the schema and db-backup's ``pg_dump`` — or an
    operator's ``psql`` — is connected as the administrator. The reset has to
    reach ``DROP SCHEMA`` anyway, which it can only do by not reaching for a
    session it may not terminate. The marker table is what makes "reached"
    observable: on a database the reset never touched, it is still there.
    """
    probe = _probe_role()
    scratch = f'inventari_sweep_reset_{_worker_tag()}'
    admin = create_engine(
        make_url(settings.DATABASE_URL).set(database='postgres'),
        isolation_level='AUTOCOMMIT',
        poolclass=NullPool,
    )
    probe_engine = create_engine(
        make_url(settings.DATABASE_URL).set(
            database=scratch, username=probe, password=_PROBE_AUTH
        ),
        poolclass=NullPool,
    )
    holder_engine = create_engine(
        make_url(settings.DATABASE_URL).set(database=scratch), poolclass=NullPool
    )
    holder = None
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP ROLE IF EXISTS {probe}'))
            conn.execute(
                text(f'CREATE ROLE {probe} LOGIN PASSWORD :auth'),
                {'auth': _PROBE_AUTH},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS {scratch} WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE {scratch} OWNER {probe}'))

        with probe_engine.connect() as conn:
            conn.execute(text('CREATE TABLE public.sweep_probe_marker (id int)'))
            conn.commit()

        holder = holder_engine.connect()
        # ``str(url)`` masks the password — the reset needs the real one.
        monkeypatch.setenv(
            'DATABASE_URL', probe_engine.url.render_as_string(hide_password=False)
        )
        yield

        with probe_engine.connect() as conn:
            leftover = conn.execute(
                text("SELECT to_regclass('public.sweep_probe_marker')")
            ).scalar()
        if expect_empty:
            assert leftover is None, (
                'the reset did not reach DROP SCHEMA: the marker table it was '
                'pointed at is still there'
            )
        else:
            assert leftover == 'sweep_probe_marker', (
                'a reset whose sweep failed must leave the schema untouched'
            )
        assert holder.execute(text('SELECT 1')).scalar() == 1, (
            "the administrator's session did not survive a reset that has no "
            'business terminating it'
        )
    finally:
        if holder is not None:
            with contextlib.suppress(Exception):
                holder.close()
        holder_engine.dispose()
        probe_engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS {scratch} WITH (FORCE)'))
            conn.execute(text(f'DROP ROLE IF EXISTS {probe}'))
        admin.dispose()


class TestTheResetReachesTheDrop:
    """The sweep is only useful if the statement after it still runs."""

    def test_the_demo_drop_completes_with_a_superuser_session_attached(
        self, monkeypatch
    ) -> None:
        """The defect, end to end.

        ``_drop_schema`` is the nightly rebuild's first step and the only one
        with nothing around it — no try, no prompt, nobody watching. With a
        superuser session in the database the sweep raised
        ``permission denied to terminate process`` and the rebuild stopped
        there: the demo kept yesterday's data.
        """
        with _a_database_the_probe_owns(monkeypatch):
            commands_demo._drop_schema()

    def test_db_reset_empties_the_database_it_was_pointed_at(self, monkeypatch) -> None:
        """The reset clears its database while another role stays connected."""
        with _a_database_the_probe_owns(monkeypatch):
            commands_db.reset(yes_i_am_sure=True)

    @pytest.mark.parametrize(
        'module',
        [commands_db, commands_demo],
        ids=['db', 'demo'],
    )
    def test_a_failed_sweep_reports_its_original_error_and_keeps_the_schema(
        self, monkeypatch, module
    ) -> None:
        monkeypatch.setattr(module, 'TERMINATE_OTHER_SESSIONS_SQL', 'SELECT 1 / 0')
        with _a_database_the_probe_owns(monkeypatch, expect_empty=False):
            with pytest.raises(DBAPIError) as error:
                if module is commands_db:
                    module.reset(yes_i_am_sure=True)
                else:
                    module._drop_schema()
            assert error.value.orig.pgcode == '22012', (
                'the original division-by-zero error must reach the caller, '
                'rather than a later aborted-transaction error from DROP SCHEMA'
            )
