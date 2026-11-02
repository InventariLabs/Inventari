"""A run's test databases wear the run's id, and the cleanup reads it back.

A worker database that another actor can delete by name while the run still
needs it is the whole defect: the documented recovery for a poisoned run is
dropping test databases, and names that every run shared let such a sweep
land on a live suite. These tests hold the two halves — the name is unique
to its run, and the sweep drops exactly the names wearing its own id.

The migration scratch databases beside the worker ones are the other half of
the same defect: named by the worker alone, they were shared by every suite
on the server and no run ever removed them, so a server accumulates one per
worker per suite.
"""

from uuid import uuid4

from sqlalchemy import create_engine, text

from app.config import settings
from app.core.db_isolation import (
    drop_run_databases,
    isolated_db_url,
    run_scoped_db_name,
)


def test_two_runs_never_share_a_worker_database_name(monkeypatch):
    monkeypatch.setenv('INVENTARI_TEST_RUN_ID', 'aaaa1111bb')
    first = run_scoped_db_name('inventari_test', 'gw3')
    monkeypatch.setenv('INVENTARI_TEST_RUN_ID', 'cccc2222dd')
    second = run_scoped_db_name('inventari_test', 'gw3')
    assert first != second, (
        'two runs on one server sharing a name is the collision that lets a '
        'recovery sweep reach a live suite'
    )


def test_the_worker_suffix_survives_and_the_controller_has_its_own(monkeypatch):
    monkeypatch.setenv('INVENTARI_TEST_RUN_ID', 'aaaa1111bb')
    worker = run_scoped_db_name('inventari_test', 'gw3')
    controller = run_scoped_db_name('inventari_test', None)
    assert worker == 'inventari_test_raaaa1111bb_gw3'
    assert controller == 'inventari_test_raaaa1111bb'
    assert controller != worker


def test_the_cleanup_drops_this_runs_databases_and_leaves_another_runs(
    engine,
):
    base = 'inventari_test_nametest'
    mine, theirs = f'{base}_rprobe11_gw0', f'{base}_rother22_gw0'
    url = settings.DATABASE_URL.rsplit('/', 1)[0]
    admin = create_engine(f'{url}/postgres', isolation_level='AUTOCOMMIT')
    try:
        with admin.connect() as conn:
            for name in (mine, theirs):
                conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
                conn.execute(text(f'CREATE DATABASE "{name}"'))

        dropped = drop_run_databases(f'{url}/anydb', base, 'probe11')

        assert dropped == [mine], 'the sweep names exactly what it dropped'
        with admin.connect() as conn:
            remaining = {
                row[0]
                for row in conn.execute(
                    text('SELECT datname FROM pg_database WHERE datname LIKE :p'),
                    {'p': f'{base}_%'},
                )
            }
        assert mine not in remaining, "this run's database is gone"
        assert theirs in remaining, (
            "a concurrent run's database must survive a sweep that is not "
            'addressed to it'
        )
    finally:
        with admin.connect() as conn:
            for name in (mine, theirs):
                conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()


def test_a_sweep_against_an_unknown_run_touches_nothing(engine):
    base = 'inventari_test_nametest'
    live = f'{base}_rlive99_gw0'
    url = settings.DATABASE_URL.rsplit('/', 1)[0]
    admin = create_engine(f'{url}/postgres', isolation_level='AUTOCOMMIT')
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{live}"'))
            conn.execute(text(f'CREATE DATABASE "{live}"'))

        dropped = drop_run_databases(f'{url}/anydb', base, uuid4().hex[:8])

        assert dropped == []
        with admin.connect() as conn:
            still_there = conn.execute(
                text('SELECT 1 FROM pg_database WHERE datname = :n'),
                {'n': live},
            ).scalar()
        assert still_there, (
            'a sweep addressed to a run nobody named leaves every database standing'
        )
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{live}"'))
        admin.dispose()


def test_the_scratch_database_is_the_runs_own_and_the_sweep_takes_it(monkeypatch):
    """The database the migration tests upgrade into wears the run id too.

    It was named by the worker alone, and no run removed it on the way out,
    so every suite left one database per worker behind — on the servers that
    hosted them, twenty-four apiece. A name that carries the run makes the
    leftover removable by the run that made it and inert to every other.
    """
    monkeypatch.setenv('PYTEST_XDIST_WORKER', 'gw3')
    monkeypatch.setenv('INVENTARI_TEST_RUN_ID', 'aaaa1111bb')
    with isolated_db_url('probe') as first:
        first_name = first.rsplit('/', 1)[1]
    monkeypatch.setenv('INVENTARI_TEST_RUN_ID', 'cccc2222dd')
    with isolated_db_url('probe') as second:
        second_name = second.rsplit('/', 1)[1]

    assert first_name == 'test_scratch_raaaa1111bb_gw3'
    assert second_name == 'test_scratch_rcccc2222dd_gw3'

    dropped = drop_run_databases(settings.DATABASE_URL, 'inventari_test', 'aaaa1111bb')
    dropped += drop_run_databases(settings.DATABASE_URL, 'inventari_test', 'cccc2222dd')

    assert sorted(dropped) == sorted([first_name, second_name]), (
        'both runs name their own scratch database, and the sweep of one run '
        'takes only what that run made'
    )


def test_a_database_from_before_the_run_ids_is_left_alone(monkeypatch):
    """The old naming is inert: no run hands it out, no sweep takes it.

    Servers still carry one ``test_scratch_gwN`` per worker per suite that ran
    before this. Clearing those is a deliberate, server-wide act rather than
    something a run may drift into, because a sweep that does not name a run
    is exactly the sweep that can delete a suite which is still running.

    The probe wears worker 999, which no machine reaches — a test that grabbed
    one of the names an old-code suite on this box really uses would itself be
    the sweep this test refuses.
    """
    url = settings.DATABASE_URL.rsplit('/', 1)[0]
    legacy = 'test_scratch_gw999'
    monkeypatch.setenv('PYTEST_XDIST_WORKER', 'gw999')
    monkeypatch.setenv('INVENTARI_TEST_RUN_ID', 'beef1234aa')
    admin = create_engine(f'{url}/postgres', isolation_level='AUTOCOMMIT')
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{legacy}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{legacy}"'))

        with isolated_db_url('probe') as mine:
            assert mine.rsplit('/', 1)[1] == 'test_scratch_rbeef1234aa_gw999'

        dropped = drop_run_databases(
            settings.DATABASE_URL, 'inventari_test', 'beef1234aa'
        )

        assert dropped == ['test_scratch_rbeef1234aa_gw999'], (
            "the sweep counts this run's scratch database among the run's own"
        )
        with admin.connect() as conn:
            still_there = conn.execute(
                text('SELECT 1 FROM pg_database WHERE datname = :n'),
                {'n': legacy},
            ).scalar()
        assert still_there, (
            'a database whose name carries no run id belongs to no run, so no '
            'run may delete it'
        )
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{legacy}" WITH (FORCE)'))
        admin.dispose()
